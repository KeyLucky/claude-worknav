#!/usr/bin/env python3
"""worknav 상태 저장소 — 스키마, 파일 잠금, 원자적 교체.

여기가 틀리면 나머지가 전부 무의미하다. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import time
from datetime import datetime
from pathlib import Path

# 파일 잠금은 플랫폼마다 다르다. 둘 다 프로세스가 죽으면 OS 가 자동으로 풀어 주므로
# 크래시 후 잠금이 남지 않는다 — 락 파일에 PID 를 적고 스테일 판정을 하는 방식보다
# 이쪽이 안전하다.
try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - 플랫폼 분기
    fcntl = None
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - 플랫폼 분기
    msvcrt = None

SCHEMA_VERSION = 1

DEFAULT_CONFIG = {
    "depth_warn": 3,
    "park_ttl_days": 7,
    "stale_open_min": 30,
    "statusline_max_width": 60,
    "title_max": 12,
}

LOCK_TIMEOUT_S = 2.0
_CYCLE_GUARD = 1000


class LockBusy(RuntimeError):
    """다른 세션이 상태 파일을 잡고 있다."""


class StateMissing(RuntimeError):
    """상태 파일이 없다 — 아직 /root 를 안 했다."""


class StateCorrupt(RuntimeError):
    """상태 파일이 깨졌다. 추측해서 복구하지 않는다."""


class UserError(RuntimeError):
    """호출자가 규칙을 어겼다 (exit 2)."""


class GateRefused(RuntimeError):
    """깊이 게이트가 막았다 (exit 3). 상태는 변경되지 않는다."""


# ---------------------------------------------------------------- 경로 해석


def project_root(start=None):
    """프로젝트 경계 = git root. 없으면 cwd.

    cwd 기준으로만 잡으면 하위 디렉터리에서 세션을 열 때 상태가 갈라진다.
    subprocess 대신 직접 거슬러 올라간다 — 상태줄은 매 렌더마다 도는 경로다.
    """
    override = os.environ.get("WORKNAV_ROOT")
    if override:
        return Path(override).resolve()
    cur = Path(start or os.getcwd()).resolve()
    for cand in [cur] + list(cur.parents):
        if (cand / ".git").exists():
            return cand
    return cur


def wn_dir(root=None):
    return (Path(root) if root else project_root()) / ".claude" / "worknav"


def state_path(root=None):
    return wn_dir(root) / "state.json"


def events_path(root=None):
    return wn_dir(root) / "events.jsonl"


def lock_path(root=None):
    return wn_dir(root) / "state.lock"


def archive_dir(root=None):
    return wn_dir(root) / "archive"


def force_utf8_output():
    """표지판 문자(⟩ › ⑂ 와 한글)를 어느 콘솔에서든 깨지지 않게 내보낸다.

    Windows 기본 콘솔 인코딩(cp949 등)에서는 이 문자들이 UnicodeEncodeError 를 낸다.
    표지판이 예외로 죽는 것보다는 대체 문자로라도 나오는 편이 낫다.
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def session_id():
    """Claude Code 가 심는 세션 식별자.

    실제 이름은 `CLAUDE_CODE_SESSION_ID` 다 — 2.1.251 훅 환경에서 실측했다.
    `CLAUDE_SESSION_ID` 는 존재하지 않아서 v0 에서는 이 값이 항상 null 이었다.
    """
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------- 읽기/쓰기


def new_state():
    return {
        "version": SCHEMA_VERSION,
        "root": None,
        "cursor": None,
        "next_id": 1,
        "config": dict(DEFAULT_CONFIG),
        "nodes": {},
    }


def load(root=None):
    path = state_path(root)
    if not path.exists():
        raise StateMissing(str(path))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StateCorrupt(str(exc)) from exc
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        raise StateCorrupt("unexpected shape: %r" % type(data).__name__)
    config = dict(DEFAULT_CONFIG)
    config.update(data.get("config") or {})
    data["config"] = config
    return data


def load_or_none(root=None):
    """표시 경로 전용. 없거나 깨졌으면 None — 추측해서 그리지 않는다."""
    try:
        return load(root)
    except (StateMissing, StateCorrupt, OSError):
        return None


def save(state, root=None):
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / ("state.json.tmp.%d" % os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    # Windows 에서는 대상 파일을 누가 읽는 중이면 replace 가 PermissionError 로 튄다
    # (POSIX 는 그냥 성공한다). 표시 쪽이 파일을 여는 시간은 밀리초 단위라 짧게 재시도한다.
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.02)


def _try_lock(handle):
    """비블로킹 배타 잠금 한 번 시도. 이미 잡혀 있으면 False."""
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            # msvcrt 는 현재 파일 위치부터 n바이트 구간을 잠근다. 해제할 때
            # 같은 구간을 지정해야 하므로 항상 0번째 1바이트로 고정한다.
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - fcntl 도 msvcrt 도 없는 플랫폼
            return True  # 잠글 수단이 없으면 막지 않는다. 길잡이가 작업을 막으면 안 된다
        return True
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return False
        raise


def _unlock(handle):
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass  # 해제 실패는 프로세스 종료 시 OS 가 정리한다


def _acquire(path, timeout=LOCK_TIMEOUT_S):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    deadline = time.monotonic() + timeout
    while True:
        try:
            if _try_lock(handle):
                return handle
        except OSError:
            handle.close()
            raise
        if time.monotonic() >= deadline:
            handle.close()
            raise LockBusy(str(path))
        time.sleep(0.02)


@contextlib.contextmanager
def edit(root=None, create=False):
    """잠금 → 읽기 → (수정) → 원자적 교체 → 해제.

    본문에서 예외가 나면 save 를 건너뛴다. 게이트 거부 시 상태 무변경이 이걸로 보장된다.
    """
    root = Path(root) if root else project_root()
    handle = _acquire(lock_path(root))
    try:
        try:
            state = load(root)
        except StateMissing:
            if not create:
                raise
            state = new_state()
        yield state
        save(state, root)
    finally:
        try:
            _unlock(handle)
        finally:
            handle.close()


def log_event(payload, root=None, session=None):
    """append-only 이벤트 로그. 사용 데이터를 여기서 걷는다.

    세션 식별자를 같이 남긴다 — Stop 훅이 "이번 세션에 무슨 일이 있었는지" 를
    세려면 남의 세션 기록과 구분할 수 있어야 한다.
    """
    root = Path(root) if root else project_root()
    path = events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), "session": session or session_id()}
    record.update(payload)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


# ---------------------------------------------------------------- 노드 조작


def alloc_id(state):
    node_id = "n%04d" % int(state.get("next_id", 1))
    state["next_id"] = int(state.get("next_id", 1)) + 1
    return node_id


def node(state, node_id):
    found = state["nodes"].get(node_id)
    if found is None:
        raise UserError("노드 없음: %s" % node_id)
    return found


def depth_of(state, node_id):
    """parent 체인으로 매번 계산한다. depth 를 저장하면 트리 조작 시 어긋난다."""
    depth = 0
    cur = node(state, node_id)["parent"]
    guard = 0
    while cur is not None:
        depth += 1
        cur = node(state, cur)["parent"]
        guard += 1
        if guard > _CYCLE_GUARD:
            raise StateCorrupt("parent cycle at %s" % node_id)
    return depth


def path_ids(state, node_id):
    chain = [node_id]
    cur = node(state, node_id)["parent"]
    guard = 0
    while cur is not None:
        chain.append(cur)
        cur = node(state, cur)["parent"]
        guard += 1
        if guard > _CYCLE_GUARD:
            raise StateCorrupt("parent cycle at %s" % node_id)
    chain.reverse()
    return chain


def add_node(state, title, parent, node_state, origin=None, auto=False):
    """auto=True 는 훅이 감지해서 담은 것. 사람이 적은 것과 구분해야
    오탐률을 나중에 실측할 수 있다."""
    title = (title or "").strip()
    if not title:
        raise UserError("제목이 비었습니다")
    node_id = alloc_id(state)
    stamp = now_iso()
    state["nodes"][node_id] = {
        "title": title,
        "parent": parent,
        "state": node_state,
        "resume_note": None,
        "origin": origin,
        "opened_at": stamp,
        "closed_at": None,
        "touched_at": stamp,
        "session_id": session_id(),
        "auto": bool(auto),
    }
    return node_id


def children(state, node_id):
    items = [
        (nid, nd) for nid, nd in state["nodes"].items() if nd.get("parent") == node_id
    ]
    items.sort(key=lambda kv: (kv[1].get("opened_at") or "", kv[0]))
    return items


def parked_nodes(state):
    items = [
        (nid, nd) for nid, nd in state["nodes"].items() if nd.get("state") == "parked"
    ]
    items.sort(key=lambda kv: (kv[1].get("opened_at") or "", kv[0]))
    return items


def open_nodes(state):
    items = [
        (nid, nd) for nid, nd in state["nodes"].items() if nd.get("state") == "open"
    ]
    items.sort(key=lambda kv: (kv[1].get("opened_at") or "", kv[0]))
    return items


def age_minutes(node_dict, ref=None):
    started = parse_iso(node_dict.get("opened_at"))
    if started is None:
        return None
    ref = ref or datetime.now().astimezone()
    return max(0.0, (ref - started).total_seconds() / 60.0)
