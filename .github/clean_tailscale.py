# -*- coding: utf-8 -*-
"""清理所有 TAILSCALE 标记块, 恢复文件到无 Tailscale 状态"""
import io
import re

FILES = [
    "Config/mihomoConfig.yaml",
    "Config/mihomoConfigLite.yaml",
    "Script/Script.js",
    "Script/mihomoScript.js",
]

PATTERN = re.compile(
    r"^[ \t]*(?:#|//) <<<TAILSCALE-(PROXY|GROUP|RULES)>>>[ \t]*\r?\n"
    r"(?s:.*?)"
    r"^[ \t]*(?:#|//) <<<TAILSCALE-\1-END>>>[ \t]*\r?\n",
    re.M,
)

for f in FILES:
    s = io.open(f, encoding="utf-8").read()
    s2, n = PATTERN.subn("", s)
    if n:
        s2 = re.sub(r"\n{3,}", "\n\n", s2)
        io.open(f, "w", encoding="utf-8", newline="").write(s2)
        print(f"cleaned {n} block(s): {f}")
    else:
        print(f"no marker: {f}")
