#!/usr/bin/env python3
"""worknav 상태줄 — 읽기 전용. 어떤 경우에도 exit 0.

틀린 표지판은 없는 표지판보다 나쁘다. 상태 파일이 없거나 깨졌으면
아무것도 출력하지 않는다. 추측해서 그리지 않는다.

Claude Code 는 statusLine 커맨드에 세션 JSON 을 stdin 으로 준다.
거기 cwd 가 들어 있으므로 그걸로 프로젝트를 찾는다 — 이 프로세스의
cwd 가 프로젝트라는 보장이 없다.
"""

from __future__ import annotations

import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _read_stdin_with_timeout(timeout):
    """stdin 을 timeout 안에 읽는다. 못 읽으면 None.

    select 를 쓰지 않는 이유는 Windows 때문이다 — 거기서는 select 가 소켓만 받아서
    파이프를 넘기면 예외가 난다. 별도 스레드에서 읽고 기다리는 쪽이 어디서나 같다.
    데몬 스레드라 시간이 지나면 그냥 두고 나가도 프로세스가 붙잡히지 않는다.
    """
    box = {}

    def worker():
        try:
            box["data"] = sys.stdin.read()
        except Exception:
            box["data"] = None

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    return box.get("data")


def read_stdin_cwd(timeout=0.2):
    try:
        if sys.stdin is None or sys.stdin.closed:
            return None
        raw = _read_stdin_with_timeout(timeout)
        if raw is None:
            return None
        payload = json.loads(raw or "{}")
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        for key in ("current_dir", "project_dir"):
            if workspace.get(key):
                return workspace[key]
    return payload.get("cwd")


def main():
    try:
        import render
        import store

        store.force_utf8_output()
        cwd = read_stdin_cwd()
        root = store.project_root(cwd) if cwd else store.project_root()
        state = store.load_or_none(root)
        if not state:
            return 0
        line = render.path_line(state)
        if line:
            sys.stdout.write(line + "\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
