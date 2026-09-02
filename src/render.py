#!/usr/bin/env python3
"""worknav 표시 — 경로 한 줄 / 전체 트리 / 보류함.

원칙: 작업 중에는 전체 트리를 그리지 않는다. 눈이 형제 노드로 가면
도구가 가지치기를 다시 부추긴다. tree() 는 /tree 와 세션 종료에서만 부른다.
"""

from __future__ import annotations

from datetime import datetime

import store

SYMBOL = {"done": "✓", "open": "●", "parked": "⑂", "dropped": "✗"}

_RESET = "\033[0m"
_DIM = "\033[90m"
_YELLOW = "\033[33m"
_RED = "\033[31m"


def depth_color(depth):
    """사람은 d4 라는 글자를 읽기 전에 색을 먼저 본다."""
    if depth <= 1:
        return _DIM
    if depth == 2:
        return ""
    if depth < 5:
        return _YELLOW
    return _RED


def particle_eul(word):
    """을/를 선택. 한글 종성이 있으면 '을'.

    숫자·영문으로 끝나면 판정이 갈리므로 '를' 로 둔다 — 조사 하나 때문에
    게이트 문구가 어색해지느니 일관되게 틀리는 편이 낫다.
    """
    if not word:
        return "를"
    code = ord(word[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return "을" if (code - 0xAC00) % 28 else "를"
    return "를"


def open_count_excluding_root(state):
    """루트는 목표 자체라 항상 열려 있다. 세면 노이즈가 된다."""
    root = state.get("root")
    return sum(1 for node_id, _ in store.open_nodes(state) if node_id != root)


def display_width(text):
    """CJK 를 2칸으로 세는 근사. 터미널 정렬용이라 근사면 충분하다."""
    width = 0
    for ch in text:
        code = ord(ch)
        wide = (
            0x1100 <= code <= 0x115F
            or 0x2E80 <= code <= 0xA4CF
            or 0xAC00 <= code <= 0xD7A3
            or 0xF900 <= code <= 0xFAFF
            or 0xFE30 <= code <= 0xFE6F
            or 0xFF00 <= code <= 0xFF60
            or 0xFFE0 <= code <= 0xFFE6
        )
        width += 2 if wide else 1
    return width


def truncate(text, limit):
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"
    return text[: limit - 1] + "…"


def path_line(state, max_width=None, color=True):
    """⟩ 논문재현 › ablation › seed고정   d2  ⑂9

    압축 규칙: 루트와 현재는 무슨 일이 있어도 남긴다.
    길을 잃는다는 건 정확히 출발지를 잊는다는 뜻이다.
    """
    if not state:
        return ""
    cursor = state.get("cursor")
    if not cursor or cursor not in state.get("nodes", {}):
        return ""

    config = state.get("config") or store.DEFAULT_CONFIG
    max_width = max_width or config.get("statusline_max_width", 60)
    title_max = config.get("title_max", 12)

    chain = store.path_ids(state, cursor)
    depth = len(chain) - 1
    parked = len(store.parked_nodes(state))
    suffix = "  d%d  ⑂%d" % (depth, parked)
    budget = max_width - display_width(suffix)

    titles = [state["nodes"][nid]["title"] for nid in chain]

    def build(kept, limit):
        """kept 는 남길 인덱스의 오름차순 목록. 끊긴 자리에만 … 를 넣는다."""
        parts = []
        previous = None
        for index in kept:
            if previous is not None and index != previous + 1:
                parts.append("…")
            parts.append(truncate(titles[index], limit))
            previous = index
        return "⟩ " + " › ".join(parts)

    # 1단계: 가운데 항목을 하나씩 버린다. 인덱스 목록이 매번 줄어드므로 반드시 끝난다.
    # 첫 항목(루트)과 마지막 항목(현재)은 pop 대상에서 구조적으로 빠진다.
    kept = list(range(len(titles)))
    limit = title_max
    while display_width(build(kept, limit)) > budget and len(kept) > 2:
        kept.pop(len(kept) // 2)

    # 2단계: 그래도 넘치면 제목 자체를 줄인다. 루트와 현재는 끝까지 남는다.
    while display_width(build(kept, limit)) > budget and limit > 4:
        limit -= 2

    line = build(kept, limit) + suffix
    if color:
        tint = depth_color(depth)
        if tint:
            line = tint + line + _RESET
    return line


def tree(state, now=None):
    if not state or not state.get("root"):
        return "(루트 없음)"
    now = now or datetime.now().astimezone()
    cursor = state.get("cursor")
    lines = []

    def emit(node_id, prefix, is_last, is_root):
        nd = state["nodes"][node_id]
        symbol = SYMBOL.get(nd.get("state"), "?")
        label = nd.get("title", "")
        if is_root:
            lines.append(label)
            branch_prefix = ""
        else:
            connector = "└─ " if is_last else "├─ "
            meta = _node_meta(nd, now)
            here = "  ← 현재" if node_id == cursor else ""
            lines.append("%s%s%s %s%s%s" % (prefix, connector, symbol, label, meta, here))
            branch_prefix = prefix + ("   " if is_last else "│  ")
        kids = store.children(state, node_id)
        for index, (kid_id, _) in enumerate(kids):
            emit(kid_id, branch_prefix, index == len(kids) - 1, False)

    emit(state["root"], "", True, True)

    open_count = open_count_excluding_root(state)
    parked = store.parked_nodes(state)
    ttl = (state.get("config") or {}).get("park_ttl_days", 7)
    expired = sum(1 for _, nd in parked if _is_expired(nd, now, ttl))
    lines.append("")
    lines.append(
        "열린 노드 %d · 보류함 %d (%d개 %d일 경과)" % (open_count, len(parked), expired, ttl)
    )
    return "\n".join(lines)


def _node_meta(nd, now):
    if nd.get("state") == "parked":
        return "   park"
    started = store.parse_iso(nd.get("opened_at"))
    ended = store.parse_iso(nd.get("closed_at")) or now
    if started is None:
        return ""
    minutes = int(max(0, (ended - started).total_seconds() // 60))
    return "   %dm" % minutes


def _is_expired(nd, now, ttl_days):
    started = store.parse_iso(nd.get("opened_at"))
    if started is None:
        return False
    return (now - started).days >= ttl_days


def inbox(state, now=None):
    if not state:
        return "(상태 없음)"
    now = now or datetime.now().astimezone()
    ttl = (state.get("config") or {}).get("park_ttl_days", 7)
    items = store.parked_nodes(state)
    if not items:
        return "보류함 비어 있음"
    lines = ["보류함 %d" % len(items)]
    for node_id, nd in items:
        started = store.parse_iso(nd.get("opened_at"))
        days = (now - started).days if started else 0
        mark = "  [만료]" if days >= ttl else ""
        origin = nd.get("origin")
        origin_title = ""
        if origin and origin in state["nodes"]:
            origin_title = " (발생: %s)" % state["nodes"][origin]["title"]
        lines.append("  %s ⑂ %s%s  %d일%s" % (node_id, nd["title"], origin_title, days, mark))
    return "\n".join(lines)


def where(state):
    if not state or not state.get("cursor"):
        return "루트 없음 — /root <목표> 로 시작하세요"
    plain = path_line(state, max_width=200, color=False)
    open_items = store.open_nodes(state)
    lines = [plain]
    if open_items:
        lines.append("열린 노드:")
        for node_id, nd in open_items:
            here = " ← 현재" if node_id == state.get("cursor") else ""
            lines.append("  %s d%d %s%s" % (node_id, store.depth_of(state, node_id), nd["title"], here))
    return "\n".join(lines)
