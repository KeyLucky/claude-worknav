#!/usr/bin/env python3
"""worknav CLI — 상태 변경의 유일한 진입점.

모델은 제목 문자열만 넘긴다. 모델이 상태를 자유서술로 만지면 스키마가 깨진다.

종료 코드
  0  성공
  2  사용자 오류 (규칙 위반)
  3  깊이 게이트 거부 — 상태 무변경
  4  상태 파일 없음 / 손상
  5  잠금 획득 실패 (다른 세션이 쓰는 중)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render  # noqa: E402
import store  # noqa: E402

EXIT_OK = 0
EXIT_USER = 2
EXIT_GATE = 3
EXIT_STATE = 4
EXIT_LOCK = 5


def _out(text):
    if text:
        print(text)


# ------------------------------------------------------------------ 명령


def cmd_root(args, root):
    with store.edit(root, create=True) as state:
        existing = state.get("root")
        if existing and existing in state["nodes"]:
            current = state["nodes"][existing]
            if current.get("state") == "open" and not args.force:
                raise store.UserError(
                    "루트 '%s' 가 아직 열려 있습니다. /pop 으로 닫거나 --force 를 쓰세요."
                    % current["title"]
                )
            _archive(root)
            state.clear()
            state.update(store.new_state())
        node_id = store.add_node(state, args.title, None, "open", origin=None)
        state["root"] = node_id
        state["cursor"] = node_id
        store.log_event({"cmd": "root", "node": node_id, "title": args.title}, root)
        _out("⌂ ROOT 설정: %s" % state["nodes"][node_id]["title"])
    return EXIT_OK


def _archive(root):
    src = store.state_path(root)
    if not src.exists():
        return
    dest_dir = store.archive_dir(root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(src, dest_dir / ("state-%s.json" % stamp))


def cmd_push(args, root):
    note = (args.resume_note or "").strip()
    if not note:
        raise store.UserError(
            "복귀지점(--resume-note)이 필요합니다. "
            "지금 노드에서 어디까지 했고 다음에 무엇을 하려 했는지 한 문장."
        )
    with store.edit(root) as state:
        cursor = _require_cursor(state)
        parent = store.node(state, cursor)
        if parent.get("state") != "open":
            raise store.UserError("현재 노드가 열려 있지 않습니다 (%s)" % parent.get("state"))

        new_depth = store.depth_of(state, cursor) + 1
        limit = state["config"]["depth_warn"]
        if new_depth >= limit and not args.force:
            gate = _gate_text(state, cursor, args.title, new_depth)
            store.log_event(
                {"cmd": "push", "result": "gate", "depth": new_depth, "title": args.title},
                root,
            )
            raise store.GateRefused(gate)

        parent["resume_note"] = note
        parent["touched_at"] = store.now_iso()
        node_id = store.add_node(state, args.title, cursor, "open", origin=cursor)
        state["cursor"] = node_id
        store.log_event(
            {
                "cmd": "push",
                "result": "forced" if (new_depth >= limit and args.force) else "ok",
                "node": node_id,
                "depth": new_depth,
                "title": args.title,
            },
            root,
        )
        _out("↓ d%d %s · 복귀지점 저장됨" % (new_depth, state["nodes"][node_id]["title"]))
    return EXIT_OK


def _gate_text(state, cursor, title, new_depth):
    parent_title = state["nodes"][cursor]["title"]
    chain = store.path_ids(state, cursor)
    lines = ["⚠ 깊이 %d 진입 시도" % new_depth, ""]
    for index, node_id in enumerate(chain):
        nd = state["nodes"][node_id]
        indent = "   " * index
        age = store.age_minutes(nd)
        meta = "  (%d분째)" % int(age) if age is not None else ""
        prefix = "ROOT  " if index == 0 else "└─ "
        lines.append("  %s%s%s%s" % (indent, prefix, nd["title"], meta))
    lines.append("  %s└─ %s   ← 지금 들어가려는 곳" % ("   " * len(chain), title))
    lines += [
        "",
        '  이게 "%s"%s 지금 막고 있습니까?' % (parent_title, render.particle_eul(parent_title)),
        "  예   → /push --force",
        "  아니오 → /park   (무응답 시 park)",
    ]
    return "\n".join(lines)


def cmd_pop(args, root):
    with store.edit(root) as state:
        cursor = _require_cursor(state)
        current = store.node(state, cursor)
        parent_id = current.get("parent")
        if parent_id is None:
            raise store.UserError("루트에서는 pop 할 수 없습니다. 작업이 끝났으면 /root 로 새로 시작하세요.")
        stamp = store.now_iso()
        current["state"] = "done"
        current["closed_at"] = stamp
        current["touched_at"] = stamp
        parent = store.node(state, parent_id)
        parent["touched_at"] = stamp
        state["cursor"] = parent_id
        note = parent.get("resume_note")
        store.log_event({"cmd": "pop", "node": cursor, "to": parent_id}, root)
        depth = store.depth_of(state, parent_id)
        tail = ' · "%s"' % note if note else " · (복귀지점 없음)"
        _out("↑ d%d %s%s" % (depth, parent["title"], tail))
    return EXIT_OK


def cmd_park(args, root):
    with store.edit(root) as state:
        cursor = _require_cursor(state)
        node_id = store.add_node(state, args.title, cursor, "parked", origin=cursor)
        # 커서는 움직이지 않는다. 이게 PARK 의 전부다.
        store.log_event({"cmd": "park", "node": node_id, "title": args.title}, root)
        count = len(store.parked_nodes(state))
        _out("⑂ 가지 담김: %s (⑂%d)" % (state["nodes"][node_id]["title"], count))
    return EXIT_OK


def cmd_resume(args, root):
    note = (args.resume_note or "").strip()
    with store.edit(root) as state:
        target = store.node(state, args.node_id)
        if target.get("state") != "parked":
            raise store.UserError("보류 상태가 아닙니다: %s (%s)" % (args.node_id, target.get("state")))
        cursor = state.get("cursor")
        if cursor and store.node(state, cursor).get("state") == "open":
            if not note:
                raise store.UserError("복귀지점(--resume-note)이 필요합니다.")
            current = store.node(state, cursor)
            current["resume_note"] = note
            current["touched_at"] = store.now_iso()
        target["state"] = "open"
        target["touched_at"] = store.now_iso()
        state["cursor"] = args.node_id
        depth = store.depth_of(state, args.node_id)
        store.log_event({"cmd": "resume", "node": args.node_id, "depth": depth}, root)
        _out("↳ d%d %s (보류함에서 꺼냄)" % (depth, target["title"]))
    return EXIT_OK


def cmd_drop(args, root):
    with store.edit(root) as state:
        target = store.node(state, args.node_id)
        if target.get("state") != "parked":
            raise store.UserError("보류 상태만 폐기할 수 있습니다: %s" % args.node_id)
        target["state"] = "dropped"
        target["closed_at"] = store.now_iso()
        store.log_event({"cmd": "drop", "node": args.node_id}, root)
        _out("✗ 폐기: %s" % target["title"])
    return EXIT_OK


def cmd_where(args, root):
    _out(render.where(store.load(root)))
    return EXIT_OK


def cmd_tree(args, root):
    _out(render.tree(store.load(root)))
    return EXIT_OK


def cmd_inbox(args, root):
    _out(render.inbox(store.load(root)))
    return EXIT_OK


def cmd_path(args, root):
    """상태줄/훅용 한 줄. 실패해도 조용히 빈 출력."""
    state = store.load_or_none(root)
    line = render.path_line(state, color=not args.no_color) if state else ""
    if line:
        print(line)
    return EXIT_OK


def cmd_stats(args, root):
    """이 도구가 실제로 쓰이고 있는지, 임계값이 맞는지를 로그에서 센다."""
    import hooklogic
    import stats

    events = stats.read_events(root)
    turns = hooklogic.load_hookstate(root).get("turns")
    state = store.load_or_none(root)
    summary = stats.summarize(events, turns)
    advice = stats.advise(summary, (state or {}).get("config"))
    _out(stats.render(summary, advice))
    return EXIT_OK


def cmd_dump(args, root):
    print(json.dumps(store.load(root), ensure_ascii=False, indent=2))
    return EXIT_OK


def _require_cursor(state):
    cursor = state.get("cursor")
    if not cursor or cursor not in state.get("nodes", {}):
        raise store.UserError("루트가 없습니다. /root <목표> 로 시작하세요.")
    return cursor


# ------------------------------------------------------------------ 진입점


def build_parser():
    parser = argparse.ArgumentParser(prog="wn", description="worknav — 작업 길잡이")
    parser.add_argument("--root", help="프로젝트 경로 (기본: git root 또는 cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("root", help="루트 목표 설정")
    p.add_argument("title")
    p.add_argument("--force", action="store_true", help="열린 루트를 보관하고 새로 시작")
    p.set_defaults(func=cmd_root)

    p = sub.add_parser("push", help="가지로 내려감 (깊이 게이트 적용)")
    p.add_argument("title")
    p.add_argument("--resume-note", required=False, default="")
    p.add_argument("--force", action="store_true", help="깊이 게이트 통과")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("pop", help="부모로 복귀")
    p.set_defaults(func=cmd_pop)

    p = sub.add_parser("park", help="보류함에 담고 커서 유지")
    p.add_argument("title")
    p.set_defaults(func=cmd_park)

    p = sub.add_parser("resume", help="보류 항목을 열고 커서 이동")
    p.add_argument("node_id")
    p.add_argument("--resume-note", required=False, default="")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("drop", help="보류 항목 폐기")
    p.add_argument("node_id")
    p.set_defaults(func=cmd_drop)

    for name, func, helptext in (
        ("where", cmd_where, "현재 경로와 열린 노드"),
        ("tree", cmd_tree, "전체 트리"),
        ("inbox", cmd_inbox, "보류함"),
        ("stats", cmd_stats, "사용 통계와 임계값 조정 근거"),
        ("dump", cmd_dump, "상태 JSON 원본"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.set_defaults(func=func)

    p = sub.add_parser("path", help="경로 한 줄 (상태줄용)")
    p.add_argument("--no-color", action="store_true")
    p.set_defaults(func=cmd_path)

    return parser


def main(argv=None):
    store.force_utf8_output()
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve() if args.root else store.project_root()
    try:
        return args.func(args, root)
    except store.GateRefused as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_GATE
    except store.UserError as exc:
        print("✗ %s" % exc, file=sys.stderr)
        return EXIT_USER
    except store.StateMissing:
        print("✗ 상태 파일이 없습니다. /root <목표> 로 시작하세요.", file=sys.stderr)
        return EXIT_STATE
    except store.StateCorrupt as exc:
        print("✗ 상태 파일이 손상됐습니다 (%s). 추측 복구하지 않습니다." % exc, file=sys.stderr)
        return EXIT_STATE
    except store.LockBusy:
        print("✗ 다른 세션이 상태 파일을 쓰는 중입니다. 잠시 후 다시.", file=sys.stderr)
        return EXIT_LOCK
    except OSError as exc:
        # 디스크가 늘 쓸 수 있는 건 아니다 — 읽기 전용 디렉터리, .claude/worknav 가
        # 파일로 존재, 디스크 가득. 사람에게 파이썬 스택을 보여줄 일이 아니다.
        print("✗ 상태 파일을 다룰 수 없습니다: %s" % exc, file=sys.stderr)
        return EXIT_STATE


if __name__ == "__main__":
    sys.exit(main())
