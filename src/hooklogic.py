#!/usr/bin/env python3
"""훅 4종의 로직. 부작용은 store 호출뿐이고 나머지는 순수 함수다.

여기 있는 함수는 전부 (payload, root) -> dict|None 형태라 훅 스크립트를
띄우지 않고도 단위 테스트할 수 있다. 훅 스크립트는 4줄짜리 진입점이다.

핵심 경계 — **PARK 은 자동으로 하고 PUSH 는 어떤 경우에도 자동으로 하지 않는다.**
park 오탐은 보류함에 쓸모없는 한 줄이 늘고 끝나지만, push 오탐은 사람을
엉뚱한 곳으로 끌고 간다. 한 번 그러면 도구 자체를 못 믿게 된다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import detect
import hookrt
import render
import store

# 자동 적재를 멈추는 보류함 크기. 이미 이만큼 쌓였으면 더 담아도 사람이 안 본다.
AUTO_PARK_LIMIT = 20

# 같은 노드에 대한 stale 알림 재발 간격(분). 매 프롬프트마다 상기시키면 무시하게 된다.
STALE_REPEAT_MIN = 15

_TAG = "[worknav]"


# ------------------------------------------------------------ 훅 전용 보조 상태


def _hookstate_path(root):
    return store.wn_dir(root) / "hookstate.json"


def load_hookstate(root):
    """알림 억제용 캐시. 진실원이 아니라서 잠그지 않고 깨져도 무해하다.

    "깨져도 무해" 하려면 모양까지 봐야 한다. 객체가 아닌 걸 그대로 돌려주면
    호출부의 `.get` 에서 예외가 나고, 훅의 fail-safe 가 그걸 삼켜서 밖에서는
    "아무것도 안 뜬다" 로만 보인다 — 원인을 짚을 단서가 없는 그 실패 모드다.
    """
    try:
        data = json.loads(_hookstate_path(root).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_hookstate(root, data):
    try:
        path = _hookstate_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / ("hookstate.json.tmp.%d" % os.getpid())
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass  # 억제 캐시를 못 써도 알림이 좀 더 나올 뿐이다


# ------------------------------------------------------------ 공통 조각


def _path_and_counts(state):
    line = render.path_line(state, max_width=200, color=False)
    open_count = render.open_count_excluding_root(state)
    parked = len(store.parked_nodes(state))
    return line, open_count, parked


def _cursor_node(state):
    cursor = state.get("cursor")
    if not cursor or cursor not in state.get("nodes", {}):
        return None, None
    return cursor, state["nodes"][cursor]


def _root_open(state):
    root_id = state.get("root")
    if not root_id or root_id not in state.get("nodes", {}):
        return False
    return state["nodes"][root_id].get("state") == "open"


# ------------------------------------------------------------ SessionStart


def session_start(payload, root):
    """복귀 배너. 상태가 없으면 침묵한다 — worknav 를 안 쓰는 프로젝트다."""
    state = store.load_or_none(root)
    if not state or not state.get("cursor"):
        return None

    line, open_count, parked = _path_and_counts(state)
    lines = ["%s %s" % (_TAG, line)]

    _, node = _cursor_node(state)
    if node and node.get("resume_note"):
        lines.append("복귀지점: %s" % node["resume_note"])

    ttl = render.cfg_int(state.get("config"), "park_ttl_days", 7)
    now = datetime.now().astimezone()
    expired = sum(
        1
        for _, nd in store.parked_nodes(state)
        if render._is_expired(nd, now, ttl)
    )
    tail = "열린 노드 %d · 보류함 %d" % (open_count, parked)
    if expired:
        tail += " (%d개 %d일 경과 — /wn-inbox 로 정리)" % (expired, ttl)
    lines.append(tail)

    if not _root_open(state):
        lines.append("루트가 닫혀 있다. 새 작업이면 /wn-root <목표> 로 시작할 것.")
    else:
        lines.append("새 의문·부가작업은 /wn-park 로 담고, 지금 노드를 막는 것만 /wn-push 로 내려간다.")

    return hookrt.context_output("SessionStart", "\n".join(lines))


# ------------------------------------------------------------ UserPromptSubmit


def on_prompt(payload, root):
    """매 프롬프트마다 현재 경로를 주입하고, 필요할 때만 한 줄 더 붙인다."""
    state = store.load_or_none(root)
    if not state:
        return None  # 이 프로젝트에서는 worknav 를 쓰지 않는다

    if not state.get("cursor") or not _root_open(state):
        return hookrt.context_output(
            "UserPromptSubmit",
            "%s 루트 목표가 없다. 작업을 시작하기 전에 /wn-root <한 줄 목표> 를 먼저 확정할 것."
            % _TAG,
        )

    line, _, _ = _path_and_counts(state)
    lines = ["%s %s" % (_TAG, line)]

    stale = _stale_notice(state, root)
    if stale:
        lines.append(stale)

    return hookrt.context_output("UserPromptSubmit", "\n".join(lines))


def _stale_notice(state, root, now=None):
    """오래 열려 있는 현재 노드를 상기시킨다.

    주제가 바뀌었는지는 판정하지 않는다 — 그건 LLM 이 필요하고 v0.5 는 정규식만 쓴다.
    시간만으로도 "끝났는데 POP 을 안 한" 경우는 대부분 걸린다.
    """
    cursor, node = _cursor_node(state)
    if not node or node.get("parent") is None:
        return None  # 루트는 목표 자체라 끝까지 열려 있다
    limit = render.cfg_int(state.get("config"), "stale_open_min", 30)
    age = store.age_minutes(node, ref=now)
    if age is None or age < limit:
        return None

    cache = load_hookstate(root)
    last = cache.get("stale_notice")
    if not isinstance(last, dict):
        last = {}
    now = now or datetime.now().astimezone()
    if last.get("node") == cursor:
        previous = store.parse_iso(last.get("at") if isinstance(last.get("at"), str) else None)
        if previous and (now - previous).total_seconds() / 60.0 < STALE_REPEAT_MIN:
            return None

    cache["stale_notice"] = {"node": cursor, "at": now.isoformat(timespec="seconds")}
    save_hookstate(root, cache)
    return '"%s" 가 %d분째 열려 있다. 끝났으면 /wn-pop 을 권할 것.' % (
        node.get("title", ""),
        int(age),
    )


# ------------------------------------------------------------ PostToolUse


def on_tool(payload, root):
    """가지 후보를 보류함에 자동으로 담는다. 커서는 절대 움직이지 않는다."""
    state = store.load_or_none(root)
    if not state or not state.get("cursor") or not _root_open(state):
        return None

    if payload.get("is_interrupt") or payload.get("stop_hook_active"):
        return None  # 사람이 끊은 것은 가지가 아니다

    # PostToolUse 는 tool_response(dict), PostToolUseFailure 는 error(str) 에
    # 내용을 담는다. 실측으로 확인한 차이다 — 둘 다 받아야 실패한 명령이 잡힌다.
    source = payload.get("tool_response")
    if not source:
        source = payload.get("error") or ""
    found = detect.detect(payload.get("tool_name"), payload.get("tool_input"), source)
    if not found:
        return None

    parked = store.parked_nodes(state)
    if len(parked) >= AUTO_PARK_LIMIT:
        return _limit_notice(root, len(parked))

    key = detect.normalize(found["title"])
    if not key:
        return None
    for _, nd in parked:
        if detect.normalize(nd.get("title")) == key:
            return None  # 같은 사건이 툴 호출마다 다시 잡히는 것을 막는다

    try:
        with store.edit(root) as live:
            cursor = live.get("cursor")
            if not cursor or cursor not in live.get("nodes", {}):
                return None
            # 잠금 안에서 다시 확인한다. 그 사이에 사람이 직접 담았을 수 있다.
            for _, nd in store.parked_nodes(live):
                if detect.normalize(nd.get("title")) == key:
                    return None
            node_id = store.add_node(
                live, found["title"], cursor, "parked", origin=cursor, auto=True
            )
            count = len(store.parked_nodes(live))
        store.log_event(
            {
                "cmd": "park",
                "result": "auto",
                "node": node_id,
                "kind": found["kind"],
                "title": found["title"],
            },
            root,
            session=payload.get("session_id"),
        )
    except (store.LockBusy, store.StateMissing, store.StateCorrupt, OSError):
        return None  # 길잡이가 작업을 막으면 안 된다

    return hookrt.message_output("⑂ 가지 담김: %s (⑂%d)" % (found["title"], count))


def _limit_notice(root, count):
    """보류함이 꽉 찼다는 안내는 세션당 한 번만 한다."""
    cache = load_hookstate(root)
    if cache.get("limit_notified"):
        return None
    cache["limit_notified"] = True
    save_hookstate(root, cache)
    return hookrt.message_output(
        "⑂ 보류함 %d개 — 자동 적재를 멈춤. /wn-inbox 로 정리할 것" % count
    )


# ------------------------------------------------------------ Stop


def on_stop(payload, root):
    if payload.get("stop_hook_active"):
        return None  # 재진입 방지

    state = store.load_or_none(root)
    if not state or not state.get("cursor"):
        return None

    cache = load_hookstate(root)
    cache.pop("limit_notified", None)  # 다음 세션에서 다시 알릴 수 있게
    save_hookstate(root, cache)

    root_id = state.get("root")
    root_title = state["nodes"][root_id]["title"] if root_id in state["nodes"] else "?"
    status = "미완" if _root_open(state) else "닫힘"
    line, open_count, parked = _path_and_counts(state)

    counts = _session_event_counts(root, payload.get("session_id"))
    lines = ["%s %s — %s" % (_TAG, root_title, status)]
    tail = "열린 노드 %d · 보류함 %d" % (open_count, parked)
    if counts.get("auto_park"):
        tail += " (자동 %d)" % counts["auto_park"]
    lines.append(tail)
    if counts.get("gate"):
        forced = counts.get("forced", 0)
        lines.append(
            "깊이 게이트 %d회 (통과 %d · 보류 %d)"
            % (counts["gate"], forced, counts["gate"] - forced)
        )
    if open_count:
        lines.append("현재: %s" % line)

    return hookrt.context_output("Stop", "\n".join(lines))


def _session_event_counts(root, session_id, tail_lines=400):
    """events.jsonl 의 끝부분만 읽어 이번 세션 통계를 센다.

    session_id 가 없으면(=CLI 로만 쓴 경우) 세지 않는다. 다른 세션 것을
    섞어 세느니 숫자를 안 보여주는 편이 낫다.
    """
    counts = {}
    if not session_id:
        return counts
    try:
        path = store.events_path(root)
        if not path.exists():
            return counts
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-tail_lines:]
    except OSError:
        return counts

    for raw in lines:
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        # 유효한 JSON 이라고 객체인 것은 아니다. `123` 한 줄도 파싱은 성공한다.
        if not isinstance(rec, dict):
            continue
        if rec.get("session") != session_id:
            continue
        result = rec.get("result")
        if rec.get("cmd") == "park" and result == "auto":
            counts["auto_park"] = counts.get("auto_park", 0) + 1
        elif rec.get("cmd") == "push":
            if result == "gate":
                counts["gate"] = counts.get("gate", 0) + 1
            elif result == "forced":
                counts["gate"] = counts.get("gate", 0) + 1
                counts["forced"] = counts.get("forced", 0) + 1
    return counts
