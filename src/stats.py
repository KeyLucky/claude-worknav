#!/usr/bin/env python3
"""events.jsonl 을 읽어 "이 도구가 실제로 쓰이고 있는가" 를 센다.

여기 있는 함수는 전부 순수 함수다. 파일을 읽는 것은 read_events 하나뿐이고
나머지는 레코드 목록만 받는다 — 그래야 지어낸 픽스처 없이도 검사할 수 있다.

측정의 한계를 먼저 적어 둔다. **재현율은 원리적으로 못 잰다.** "실제로 생긴
가지 수" 라는 분모를 아무도 모르기 때문이다. 그래서 아래 지표는 전부 대리
지표다. 다만 "주입은 됐는데 한 번도 안 불렀다" 같은 것은 확실히 말해 주고,
임계값을 조정할 근거로는 그것으로 충분하다.
"""

from __future__ import annotations

import json

import store

# 이 개수 미만이면 비율을 말하지 않는다. 표본 2개로 "60%" 라고 하면
# 그 숫자를 근거로 임계값을 바꾸게 된다.
MIN_SAMPLES = 5


def read_events(root=None, limit=20000):
    """append-only 로그를 관대하게 읽는다. 깨진 줄은 건너뛴다.

    유효한 JSON 이라고 객체인 것은 아니다 — `123` 한 줄도 파싱은 성공한다.
    Stop 훅에서 실제로 이것 때문에 죽은 적이 있다.
    """
    try:
        path = store.events_path(root)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.readlines()[-limit:]
    except OSError:
        return []

    out = []
    for line in raw:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * pct))
    return ordered[idx]


def summarize(events, turns=None):
    """레코드 목록 → 지표 묶음."""
    turns = turns if isinstance(turns, dict) else {}

    counts = {}
    gate = forced = 0
    parked, resumed = set(), set()
    push_ts, dwell = {}, []
    acted_sessions = set()
    sessions = set()

    for rec in events:
        cmd = rec.get("cmd")
        if not isinstance(cmd, str):
            continue
        result = rec.get("result")
        # 게이트에 거절당한 push 는 상태를 한 글자도 안 바꾼 시도다. 이걸
        # 실행으로 세면 "규칙은 주입됐는데 한 번도 안 불렀다" 라는 가장 중요한
        # 신호가 거절당한 시도만으로 지워진다.
        refused = cmd == "push" and result == "gate"
        if not refused:
            counts[cmd] = counts.get(cmd, 0) + 1
        session = rec.get("session")
        if isinstance(session, str) and session:
            sessions.add(session)
            if not refused and cmd in ("push", "park", "pop", "resume", "drop"):
                acted_sessions.add(session)

        node = rec.get("node")
        when = store.parse_iso(rec.get("ts") if isinstance(rec.get("ts"), str) else None)

        if cmd == "push":
            if result in ("gate", "forced"):
                gate += 1
            if result == "forced":
                forced += 1
            if node and when:
                push_ts[node] = when
        elif cmd == "pop":
            # pop 레코드의 node 는 "닫힌 노드" 다. 그 노드의 push 시각과 짝지어
            # 체류시간을 낸다. 짝이 없으면(이전 세션의 노드) 그냥 버린다.
            start = push_ts.pop(node, None)
            if start and when:
                dwell.append((when - start).total_seconds() / 60.0)
        elif cmd == "park":
            if node:
                parked.add(node)
            if result == "auto":
                counts["park_auto"] = counts.get("park_auto", 0) + 1
        elif cmd == "resume":
            if node:
                resumed.add(node)

    total_turns = 0
    for value in turns.values():
        try:
            total_turns += int(value)
        except (TypeError, ValueError):
            continue

    actions = sum(counts.get(k, 0) for k in ("push", "park", "pop", "resume", "drop"))
    return {
        "sessions": len(sessions),
        "turns": total_turns,
        "turn_sessions": len(turns),
        "acted_sessions": len(acted_sessions),
        "counts": counts,
        "actions": actions,
        "gate": gate,
        "forced": forced,
        "parked": len(parked),
        "resumed": len(parked & resumed),
        "dwell_p50": _percentile(dwell, 0.5),
        "dwell_p90": _percentile(dwell, 0.9),
        "dwell_n": len(dwell),
    }


def advise(summary, config=None):
    """지표에서 임계값 조정 근거만 뽑는다. 표본이 모자라면 아무 말도 안 한다."""
    config = config or {}

    def cfg(key, default):
        try:
            return int(config.get(key, default))
        except (TypeError, ValueError):
            return default

    out = []

    # 이게 가장 중요한 신호다. 규칙은 넣었는데 한 번도 안 불렀다면
    # 임계값을 어떻게 만지든 소용이 없다.
    if summary["turns"] >= 20 and summary["actions"] == 0:
        out.append("규칙을 %d턴 주입했는데 판정 명령이 0회다. 임계값이 아니라 규칙 자체가 안 먹고 있다."
                   % summary["turns"])

    if summary["gate"] >= MIN_SAMPLES:
        ratio = summary["forced"] / float(summary["gate"])
        warn = cfg("depth_warn", 3)
        if ratio >= 0.6:
            out.append("게이트 %d회 중 %.0f%% 를 force 로 통과했다. depth_warn 을 %d 로 올리는 것을 검토."
                       % (summary["gate"], ratio * 100, warn + 1))
        elif ratio <= 0.2:
            out.append("게이트 %d회 중 force 는 %.0f%% 다. depth_warn %d 이 잘 맞는다."
                       % (summary["gate"], ratio * 100, warn))

    if summary["parked"] >= 10:
        ratio = summary["resumed"] / float(summary["parked"])
        if ratio <= 0.1:
            out.append("보류함에 담은 %d개 중 %.0f%% 만 다시 꺼냈다. 보류함이 쓰레기통이 되고 있다 — park_ttl_days 를 줄일 것."
                       % (summary["parked"], ratio * 100))

    if summary["dwell_n"] >= MIN_SAMPLES:
        limit = cfg("stale_open_min", 30)
        p90 = summary["dwell_p90"]
        if p90 is not None and p90 < limit:
            out.append("노드 체류시간 p90 이 %.0f분인데 stale_open_min 은 %d분이다. 알림이 거의 안 뜬다 — 낮출 것."
                       % (p90, limit))

    if not out:
        out.append("아직 판단할 만큼 쌓이지 않았다. 며칠 더 쓰고 다시 볼 것.")
    return out


def render(summary, advice):
    lines = []
    lines.append("세션 %d · 규칙 주입 %d턴 (기록된 세션 %d)"
                 % (summary["sessions"], summary["turns"], summary["turn_sessions"]))

    counts = summary["counts"]
    auto = counts.get("park_auto", 0)
    lines.append("판정 %d회 — push %d · park %d(자동 %d) · pop %d · resume %d · drop %d"
                 % (summary["actions"], counts.get("push", 0), counts.get("park", 0), auto,
                    counts.get("pop", 0), counts.get("resume", 0), counts.get("drop", 0)))

    if summary["gate"]:
        lines.append("깊이 게이트 %d회 · force 통과 %d회"
                     % (summary["gate"], summary["forced"]))
    if summary["parked"]:
        lines.append("보류함 적재 %d개 · 다시 꺼냄 %d개" % (summary["parked"], summary["resumed"]))
    if summary["dwell_n"]:
        lines.append("노드 체류시간 p50 %.0f분 · p90 %.0f분 (표본 %d)"
                     % (summary["dwell_p50"], summary["dwell_p90"], summary["dwell_n"]))
    if summary["turn_sessions"]:
        lines.append("판정이 한 번도 없던 세션 %d / %d"
                     % (summary["turn_sessions"] - summary["acted_sessions"],
                        summary["turn_sessions"]))

    lines.append("")
    for line in advice:
        lines.append("· %s" % line)
    return "\n".join(lines)
