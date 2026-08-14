#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
幂等注入 Tailscale 自定义配置到 Config/*.yaml 与 Script/*.js（全量版/精简版）

用法: python3 .github/apply-tailscale.py

设计说明:
- 每个注入块用成对标记包裹 (<<<TAILSCALE-XXX>>> / <<<TAILSCALE-XXX-END>>>)
- 若标记已存在: 直接替换标记之间的内容(可自动更新 auth-key 等);
  标记匹配容忍任意行首缩进, 兼容上游 merge 后残留的旧格式标记
- 若标记不存在: 在锚点位置插入完整块
- 注入块内容与 prettier 输出保持一致, 避免 format job 来回改动
- 可重复执行, 用于 GitHub Actions 同步上游后重新注入自定义改动
- 同时修补 Test/suites/integration.js, 将 TAILSCALE 节点从测试的订阅节点集合中排除

auth-key 变更时, 只需修改下方 AUTH_KEY 并重新运行本脚本。
"""
import os
import re
import sys

AUTH_KEY = "tskey-auth-kBPsdWyFE911CNTRL-EF8jUxZQb2cYWy3uY8My2cmMLUUyFpX6"

ICON_NETWORK = "https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/Network.png"
ICON_CHINA_MAP = "https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/China_Map.png"
HOSTNAME = "flclash-android"

_MARKER_RE_CACHE = {}


def _marker_re(marker):
    """标记正则: 行首任意缩进 + 标记文本(缩进无关, 兼容新旧格式)"""
    if marker not in _MARKER_RE_CACHE:
        _MARKER_RE_CACHE[marker] = re.compile(
            r"^[ \t]*" + re.escape(marker) + r"[ \t]*$", re.M
        )
    return _MARKER_RE_CACHE[marker]


# ---------------------------------------------------------------- 注入块定义
# 注意: 块内容 = prettier 格式化后的最终形态, 修改时请先跑 prettier 确认

def yaml_proxy_block():
    return f"""  # <<<TAILSCALE-PROXY>>>
  - name: TAILSCALE
    type: tailscale
    hostname: {HOSTNAME}
    auth-key: {AUTH_KEY}
    control-url: https://controlplane.tailscale.com
    state-dir: ./tailscale
    ephemeral: false
    udp: true
    accept-routes: true
    ip-version: ipv4-prefer
# <<<TAILSCALE-PROXY-END>>>"""


def yaml_group_block():
    return f"""  # <<<TAILSCALE-GROUP>>>
  # Tailscale 策略组
  - name: 'Tailscale'
    <<: *group_common_select
    proxies: ['TAILSCALE', '直连']
    icon: '{ICON_NETWORK}'
  # <<<TAILSCALE-GROUP-END>>>"""


def yaml_rules_block():
    return """  # <<<TAILSCALE-RULES>>>
  # Tailscale 网段优先（置于最前）
  - IP-CIDR,100.64.0.0/10,Tailscale,no-resolve
  - IP-CIDR,100.100.100.100/32,Tailscale,no-resolve
  - DOMAIN-SUFFIX,ts.net,Tailscale
  # <<<TAILSCALE-RULES-END>>>"""


def js_rules_block():
    return """    // <<<TAILSCALE-RULES>>>
    // Tailscale 网段优先（置于最前）
    'IP-CIDR,100.64.0.0/10,Tailscale,no-resolve',
    'IP-CIDR,100.100.100.100/32,Tailscale,no-resolve',
    'DOMAIN-SUFFIX,ts.net,Tailscale',
    // <<<TAILSCALE-RULES-END>>>"""


def js_proxy_block():
    # 适配上游新结构: 脚本在 main() 末尾用 newConfig['proxies'] 汇总节点
    return f"""  // <<<TAILSCALE-PROXY>>>
  // 幂等: 脚本被重复应用(全局+订阅)时, 去重所有节点并注入 TAILSCALE
  const seenNames = new Set();
  newConfig['proxies'] = newConfig['proxies'].filter((p) => {{
    if (!p || !p.name) return true;
    if (seenNames.has(p.name)) return false;
    seenNames.add(p.name);
    return true;
  }});
  if (!newConfig['proxies'].some((p) => p.name === 'TAILSCALE')) {{
    newConfig['proxies'].push({{
      name: 'TAILSCALE',
      type: 'tailscale',
      hostname: '{HOSTNAME}',
      'auth-key': '{AUTH_KEY}',
      'control-url': 'https://controlplane.tailscale.com',
      'state-dir': './tailscale',
      ephemeral: false,
      udp: true,
      'accept-routes': true,
      'ip-version': 'ipv4-prefer',
    }});
  }}
  // <<<TAILSCALE-PROXY-END>>>"""


def js_group_block():
    return f"""  // <<<TAILSCALE-GROUP>>>
  // functionalGroups 每次运行都会重新构建, 天然唯一, 直接追加即可
  functionalGroups.push({{
    ...selectBaseOption,
    name: 'Tailscale',
    proxies: ['TAILSCALE', '直连'],
    icon: '{ICON_NETWORK}',
  }});
  // <<<TAILSCALE-GROUP-END>>>"""


def js_test_proxies_block():
    # 上游测试把 out.proxies 里非 direct 的节点都当作订阅节点断言,
    # 需将注入的 TAILSCALE 排除, 否则 ip-version 相关用例失败
    return """  // <<<TAILSCALE-TEST>>>
  // Tailscale 节点不属于订阅节点, 从测试的订阅节点集合中排除
  const nonDirectProxies = (out) => out.proxies.filter((p) => p.type !== 'direct' && p.name !== 'TAILSCALE');
  // <<<TAILSCALE-TEST-END>>>"""


def js_test_chain_block():
    # 链式中转组只包含订阅节点, TAILSCALE 注入在链组构建之后, 不参与计数
    return """      // <<<TAILSCALE-TEST-CHAIN>>>
      const subscriptionNodes = out.proxies
        .filter((p) => p.type !== 'direct' && p.name !== 'TAILSCALE' && !customNodeNames.has(p.name))
        .map((p) => p.name);
      // <<<TAILSCALE-TEST-CHAIN-END>>>"""


# ---------------------------------------------------------------- 目标文件配置

# (文件路径, 注入块列表)
# 每个注入块: (begin_marker, end_marker, block, anchor, replace_anchor, blank_line)
#   anchor 在块不存在时使用: 将块插入到 anchor 之后
#   replace_anchor=True: 用 block 直接替换 anchor(改写既有语句)
#   blank_line=False: anchor 与块之间不插空行(数组/列表首元素, prettier 会移除空行)
TARGETS = [
    (
        "Config/mihomoConfig.yaml",
        [
            ("# <<<TAILSCALE-PROXY>>>", "# <<<TAILSCALE-PROXY-END>>>",
             yaml_proxy_block(),
             "  - { name: '🇨🇳 直连 | 双栈', type: direct }\n"),
            ("# <<<TAILSCALE-GROUP>>>", "# <<<TAILSCALE-GROUP-END>>>",
             yaml_group_block(),
             f"    icon: '{ICON_CHINA_MAP}'\n"),
            ("# <<<TAILSCALE-RULES>>>", "# <<<TAILSCALE-RULES-END>>>",
             yaml_rules_block(),
             "rules:\n", False, False),
        ],
    ),
    (
        "Config/mihomoConfigLite.yaml",
        [
            ("# <<<TAILSCALE-PROXY>>>", "# <<<TAILSCALE-PROXY-END>>>",
             yaml_proxy_block(),
             "  - { name: '🇨🇳 直连 | 双栈', type: direct }\n"),
            ("# <<<TAILSCALE-GROUP>>>", "# <<<TAILSCALE-GROUP-END>>>",
             yaml_group_block(),
             f"    icon: '{ICON_CHINA_MAP}'\n"),
            ("# <<<TAILSCALE-RULES>>>", "# <<<TAILSCALE-RULES-END>>>",
             yaml_rules_block(),
             "rules:\n", False, False),
        ],
    ),
    (
        "Script/mihomoScript.js",
        [
            ("// <<<TAILSCALE-RULES>>>", "// <<<TAILSCALE-RULES-END>>>",
             js_rules_block(),
             "  newConfig['rules'] = [\n", False, False),
            ("// <<<TAILSCALE-PROXY>>>", "// <<<TAILSCALE-PROXY-END>>>",
             js_proxy_block(),
             "  newConfig['proxies'] = [...customProxies, ...mappedProxies, ...directProxies];\n"),
            ("// <<<TAILSCALE-GROUP>>>", "// <<<TAILSCALE-GROUP-END>>>",
             js_group_block(),
             "      icon: 'https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/China_Map.png',\n      hidden: hideManualSelectGroupEnabled,\n    },\n  );\n"),
        ],
    ),
    (
        "Script/Script.js",
        [
            ("// <<<TAILSCALE-RULES>>>", "// <<<TAILSCALE-RULES-END>>>",
             js_rules_block(),
             "  newConfig['rules'] = [\n", False, False),
            ("// <<<TAILSCALE-PROXY>>>", "// <<<TAILSCALE-PROXY-END>>>",
             js_proxy_block(),
             "  newConfig['proxies'] = [...customProxies, ...mappedProxies, ...directProxies];\n"),
            ("// <<<TAILSCALE-GROUP>>>", "// <<<TAILSCALE-GROUP-END>>>",
             js_group_block(),
             "      icon: 'https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/China_Map.png',\n      hidden: hideManualSelectGroupEnabled,\n    },\n  );\n"),
        ],
    ),
    (
        "Test/suites/integration.js",
        [
            ("// <<<TAILSCALE-TEST>>>", "// <<<TAILSCALE-TEST-END>>>",
             js_test_proxies_block(),
             "  const nonDirectProxies = (out) => out.proxies.filter((p) => p.type !== 'direct');\n",
             True),
            ("// <<<TAILSCALE-TEST-CHAIN>>>", "// <<<TAILSCALE-TEST-CHAIN-END>>>",
             js_test_chain_block(),
             "      const subscriptionNodes = out.proxies\n        .filter((p) => p.type !== 'direct' && !customNodeNames.has(p.name))\n        .map((p) => p.name);\n",
             True),
        ],
    ),
]


# ---------------------------------------------------------------- 注入逻辑

def apply_block(text, begin, end, block, anchor, replace_anchor=False, blank_line=True):
    """若标记已存在则整体替换, 否则在 anchor 后插入。返回 (新文本, 是否修改)

    - 标记按整行匹配且容忍任意行首缩进(兼容旧格式标记的过渡替换)
    - replace_anchor=True 时用 block 直接替换 anchor(适用于需要改写既有语句的场景)
    - blank_line=False 时 anchor 与 block 之间不插入空行
    """
    block = block.strip("\n") + "\n"
    begin_re = _marker_re(begin)
    end_re = _marker_re(end)

    m = begin_re.search(text)
    if m:
        begin_start = m.start()
        # blank_line=False 的块(数组/列表首元素)不允许前置空行,
        # 替换时吞掉标记前残留的一个空行(旧格式注入遗留)
        if not blank_line and text[begin_start - 2:begin_start] == "\n\n":
            begin_start -= 1
        m_end = end_re.search(text, m.end())
        if not m_end:
            raise RuntimeError(f"标记 {begin} 缺少结束标记 {end}")
        line_end = text.find("\n", m_end.end())
        if line_end == -1:
            line_end = len(text)
        else:
            line_end += 1
        return text[:begin_start] + block + text[line_end:], True

    if anchor not in text:
        raise RuntimeError(f"锚点未找到: {anchor[:60]!r} ({begin})")
    if replace_anchor:
        return text.replace(anchor, block, 1), True
    sep = "" if not blank_line else "\n"
    return text.replace(anchor, anchor + sep + block, 1), True


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    changed = False
    for rel_path, blocks in TARGETS:
        path = os.path.join(repo_root, rel_path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for begin, end, block, anchor, *rest in blocks:
            text, _ = apply_block(text, begin, end, block, anchor,
                                  rest[0] if len(rest) > 0 else False,
                                  rest[1] if len(rest) > 1 else True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        changed = True
        print(f"patched: {rel_path}")
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
