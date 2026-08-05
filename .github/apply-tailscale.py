#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
幂等注入 Tailscale 自定义配置到 Config/*.yaml 与 Script/*.js（全量版/精简版）

用法: python3 .github/apply-tailscale.py

设计说明:
- 每个注入块用成对标记包裹 (<<<TAILSCALE-XXX>>> / <<<TAILSCALE-XXX-END>>>)
- 若标记已存在: 直接替换标记之间的内容(可自动更新 auth-key 等)
- 若标记不存在: 在锚点位置插入完整块
- 可重复执行, 用于 GitHub Actions 同步上游后重新注入自定义改动

auth-key 变更时, 只需修改下方 AUTH_KEY 并重新运行本脚本。
"""
import os
import sys

AUTH_KEY = "tskey-auth-kBPsdWyFE911CNTRL-EF8jUxZQb2cYWy3uY8My2cmMLUUyFpX6"

ICON_NETWORK = "https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/Network.png"
ICON_CHINA_MAP = "https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/China_Map.png"
HOSTNAME = "flclash-android"

# ---------------------------------------------------------------- 注入块定义

def yaml_proxy_block():
    return f"""# <<<TAILSCALE-PROXY>>>
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
    return f"""# <<<TAILSCALE-GROUP>>>
  # Tailscale 策略组
  - name: 'Tailscale'
    <<: *group_common_select
    proxies:
      [
        'TAILSCALE',
        '直连',
      ]
    icon: '{ICON_NETWORK}'
# <<<TAILSCALE-GROUP-END>>>"""


def yaml_rules_block():
    return """# <<<TAILSCALE-RULES>>>
  # Tailscale 网段优先（置于最前）
  - IP-CIDR,100.64.0.0/10,Tailscale,no-resolve
  - IP-CIDR,100.100.100.100/32,Tailscale,no-resolve
  - DOMAIN-SUFFIX,ts.net,Tailscale
# <<<TAILSCALE-RULES-END>>>"""


def js_rules_block():
    return """  // <<<TAILSCALE-RULES>>>
  // Tailscale 网段优先（置于最前）
  'IP-CIDR,100.64.0.0/10,Tailscale,no-resolve',
  'IP-CIDR,100.100.100.100/32,Tailscale,no-resolve',
  'DOMAIN-SUFFIX,ts.net,Tailscale',
  // <<<TAILSCALE-RULES-END>>>"""


def js_proxy_block():
    return f"""  // <<<TAILSCALE-PROXY>>>
  // 幂等: 脚本被重复应用(全局+订阅)时, 去重所有节点并注入 TAILSCALE
  if (!Array.isArray(config.proxies)) {{
    config.proxies = [];
  }}
  const seenNames = new Set();
  config.proxies = config.proxies.filter((p) => {{
    if (!p || !p.name) return true;
    if (seenNames.has(p.name)) return false;
    seenNames.add(p.name);
    return true;
  }});
  if (!config.proxies.some((p) => p.name === 'TAILSCALE')) {{
    config.proxies.push({{
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


# ---------------------------------------------------------------- 目标文件配置

# (文件路径, 注入块列表)
# 每个注入块: (begin_marker, end_marker, block, anchor)
#   anchor 在块不存在时使用: 将块插入到 anchor 之后
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
             "rules:\n"),
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
             "rules:\n"),
        ],
    ),
    (
        "Script/mihomoScript.js",
        [
            ("  // <<<TAILSCALE-RULES>>>", "  // <<<TAILSCALE-RULES-END>>>",
             js_rules_block(),
             "const rules = [\n"),
            ("  // <<<TAILSCALE-PROXY>>>", "  // <<<TAILSCALE-PROXY-END>>>",
             js_proxy_block(),
             "      name: '🇨🇳 直连 | 双栈',\n      type: 'direct',\n    },\n  );"),
            ("  // <<<TAILSCALE-GROUP>>>", "  // <<<TAILSCALE-GROUP-END>>>",
             js_group_block(),
             f"    icon: '{ICON_CHINA_MAP}',\n  }});"),
        ],
    ),
    (
        "Script/Script.js",
        [
            ("  // <<<TAILSCALE-RULES>>>", "  // <<<TAILSCALE-RULES-END>>>",
             js_rules_block(),
             "const rules = [\n"),
            ("  // <<<TAILSCALE-PROXY>>>", "  // <<<TAILSCALE-PROXY-END>>>",
             js_proxy_block(),
             "      name: '🇨🇳 直连 | 双栈',\n      type: 'direct',\n    },\n  );"),
            ("  // <<<TAILSCALE-GROUP>>>", "  // <<<TAILSCALE-GROUP-END>>>",
             js_group_block(),
             f"    icon: '{ICON_CHINA_MAP}',\n  }});"),
        ],
    ),
]


# ---------------------------------------------------------------- 注入逻辑

def apply_block(text, begin, end, block, anchor):
    """若标记已存在则整体替换, 否则在 anchor 后插入。返回 (新文本, 是否修改)"""
    block = block.strip("\n") + "\n"
    start = text.find(begin)
    if start != -1:
        end_pos = text.find(end, start)
        if end_pos == -1:
            raise RuntimeError(f"标记 {begin} 缺少结束标记 {end}")
        end_pos += len(end)
        return text[:start] + block + text[end_pos:], True
    if anchor not in text:
        raise RuntimeError(f"锚点未找到: {anchor[:60]!r} ({begin})")
    return text.replace(anchor, anchor + "\n" + block, 1), True


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    changed = False
    for rel_path, blocks in TARGETS:
        path = os.path.join(repo_root, rel_path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for begin, end, block, anchor in blocks:
            text, _ = apply_block(text, begin, end, block, anchor)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        changed = True
        print(f"patched: {rel_path}")
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
