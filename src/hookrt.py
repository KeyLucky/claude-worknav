#!/usr/bin/env python3
"""훅 공통 런타임 — stdin 계약, 출력 예산, fail-safe.

규약은 하나뿐이다: **길잡이가 작업을 막으면 안 된다.**
어떤 예외가 나도 exit 0 이고 stderr 로 아무것도 새지 않는다.
상태 파일이 없거나 잠겨 있으면 조용히 아무것도 하지 않는다.

stdin/stdout 계약은 Claude Code 2.1.251 에서 실측했다.
  입력  {"session_id","cwd","hook_event_name",...} — 이벤트별 추가 필드
  출력  {"systemMessage": "사용자에게 보이는 한 줄"}
        {"hookSpecificOutput": {"hookEventName": ..., "additionalContext": "모델에 주입"}}
"""

from __future__ import annotations

import json
import os
import sys
import threading

# UserPromptSubmit/SessionStart 주입 상한 (문자).
# 400 이었는데 520 으로 올렸다. 분기규칙을 매 턴 같이 넣기로 하면서 경로 한 줄
# 140 + 규칙 ~196(설치 경로가 길면 더) + stale 80 이 한 번에 들어가야 하는데,
# 400 이면 설치 위치에 따라 규칙 끝줄이 잘린다. 잘린 규칙은 없는 규칙보다 나쁘다.
CONTEXT_BUDGET = 520
MESSAGE_BUDGET = 80    # PostToolUse/Stop 한 줄 상한 (문자)
STDIN_TIMEOUT_S = 1.0


def _read_stdin(timeout=STDIN_TIMEOUT_S):
    """stdin 을 timeout 안에 읽는다. 못 읽으면 None.

    select 를 안 쓰는 이유는 Windows 다 — 거기 select 는 소켓만 받아서
    파이프를 넘기면 예외가 난다. 데몬 스레드는 어디서나 같게 동작하고,
    시간이 지나면 그냥 두고 나가도 프로세스가 붙잡히지 않는다.
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


def read_payload():
    try:
        if sys.stdin is None or sys.stdin.closed:
            return {}
        raw = _read_stdin()
        if not raw:
            return {}
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def payload_root(payload):
    """훅이 실행되는 프로세스의 cwd 가 프로젝트라는 보장이 없다.

    stdin 의 cwd 를 우선 쓴다 — 실측 결과 모든 훅 이벤트에 들어 있다.
    """
    import store

    cwd = payload.get("cwd")
    return store.project_root(cwd) if cwd else store.project_root()


def clip_line(text, budget=MESSAGE_BUDGET):
    """한 줄, budget 자. 훅 출력이 길어지면 사람이 읽지 않고 넘긴다."""
    if not text:
        return ""
    line = " ".join(str(text).split())
    if len(line) > budget:
        line = line[: budget - 1] + "…"
    return line


def clip_context(text, budget=CONTEXT_BUDGET):
    """여러 줄 허용, 총량만 제한. 자를 때는 줄 단위로 버린다 —
    문장 중간에서 끊긴 지시는 모델을 헷갈리게 한다."""
    if not text:
        return ""
    text = str(text).rstrip()
    if len(text) <= budget:
        return text
    kept = []
    used = 0
    for line in text.split("\n"):
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept) if kept else text[:budget]


def context_output(event_name, text):
    text = clip_context(text)
    if not text:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }


def message_output(text):
    text = clip_line(text)
    if not text:
        return None
    return {"systemMessage": text}


def debug_enabled():
    return bool(os.environ.get("WORKNAV_HOOK_DEBUG"))


def run(handler, event_name):
    """훅 진입점. handler(payload, root) -> dict | None.

    stderr 를 먼저 봉인한다. 훅의 stderr 는 세션 화면으로 새기 때문에,
    길잡이의 내부 사정이 작업 중인 사람 눈에 보이면 안 된다.

    다만 이 침묵에는 대가가 있다. 개발 중에 `str` 에 `.get` 을 부르는 버그가
    있었는데 fail-safe 가 예외를 삼켜서, 밖에서는 "아무것도 안 담긴다" 로만
    보였다. 원인을 짚을 단서가 없다. 그래서 WORKNAV_HOOK_DEBUG=1 이면
    예외를 그대로 올려서 터지게 둔다 — 진단할 때만 쓴다.
    """
    debug = debug_enabled()
    if not debug:
        try:
            sys.stderr = open(os.devnull, "w")
        except Exception:
            pass

    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import store

        store.force_utf8_output()
        payload = read_payload()
        result = handler(payload, payload_root(payload))
        if result:
            sys.stdout.write(json.dumps(result, ensure_ascii=False))
    except Exception:
        if debug:
            import traceback

            traceback.print_exc(file=sys.__stderr__)
            return 1
        # 길잡이 실패가 작업을 막으면 안 된다
    return 0
