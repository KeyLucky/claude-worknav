#!/usr/bin/env python3
"""파이썬 렌더러의 출력을 JSON 으로 뱉는다 — JS 이식본과 대조하기 위한 도구.

stdin: [{"name": ..., "state": {...}}, ...]
stdout: {"name": {"path": ..., "tree": ..., "inbox": ...}, ...}
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import render  # noqa: E402
import store  # noqa: E402

NOW = datetime.fromisoformat("2026-09-02T12:00:00+09:00")


def main():
    cases = json.loads(sys.stdin.read())
    out = {}
    for case in cases:
        state = case["state"]
        config = dict(store.DEFAULT_CONFIG)
        config.update(state.get("config") or {})
        state["config"] = config
        out[case["name"]] = {
            "path": render.path_line(state, color=False),
            "tree": render.tree(state, now=NOW),
            "inbox": render.inbox(state, now=NOW),
            "open_count": render.open_count_excluding_root(state),
        }
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
