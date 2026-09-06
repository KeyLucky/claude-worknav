#!/usr/bin/env python3
"""worknav 자가진단 — "설정은 맞는데 왜 안 뜨지" 를 이름 붙은 원인으로 바꾼다.

설계 원칙이 하나다. **설정을 읽지 말고 실제로 돌려본다.**
이 프로젝트에서 겪은 실패는 전부 "등록은 돼 있는데 실제로는 안 돈다" 였다 —
str 에 .get 을 부르던 버그, PostToolUseFailure 누락, 환경변수 이름 오타,
낡은 마켓플레이스 사본, 소스보다 오래된 .vsix. 매니페스트만 확인하는 진단은
그중 하나도 못 잡았을 것이다.

두 번째 원칙: **진단이 상태를 바꾸면 안 된다.** 훅을 실제로 구동하는데,
그중 on_tool 은 보류함에 담는 부작용이 있다. 그래서 훅은 전부 임시 프로젝트를
가리키게 해서 돌린다 — 사용자 상태 파일은 읽기만 한다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import render
import store

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

_SYMBOL = {OK: "✓", WARN: "!", FAIL: "✗", SKIP: "·"}

# 훅 하나가 이보다 오래 걸리면 매 툴 호출마다 체감된다.
HOOK_SLOW_MS = 400
HOOK_TIMEOUT_S = 10


def _finding(key, status, title, detail="", action=""):
    return {
        "key": key,
        "status": status,
        "title": title,
        "detail": detail,
        "action": action,
    }


# ---------------------------------------------------------------- 배치 탐색


def plugin_root():
    """이 파일 기준으로 플러그인 루트를 찾는다.

    배치가 둘이다 — 플러그인(hooks/ 와 src/ 가 형제)과 install.sh(한 폴더에
    평평하게). 어느 쪽인지 알아야 훅 스크립트를 찾을 수 있다.
    """
    here = Path(__file__).resolve().parent
    if (here.parent / "hooks").is_dir():
        return here.parent
    return here


def hook_scripts():
    root = plugin_root()
    found = {}
    for name in ("session_start", "on_prompt", "on_tool", "on_stop"):
        for cand in (root / "hooks" / (name + ".py"), root / (name + ".py")):
            if cand.is_file():
                found[name] = cand
                break
    return found


def claude_home():
    return Path(os.path.expanduser("~")) / ".claude"


# ---------------------------------------------------------------- 검사 1: 설치


def check_layout():
    root = plugin_root()
    scripts = hook_scripts()
    kind = "플러그인" if (root / "hooks").is_dir() else "install.sh 배치"
    cached = ".claude/plugins/cache" in str(root)

    out = []
    if len(scripts) == 4:
        out.append(
            _finding(
                "layout", OK, "설치",
                "%s · 훅 스크립트 4개 · %s" % (kind, "플러그인 캐시" if cached else str(root)),
            )
        )
    else:
        out.append(
            _finding(
                "layout", FAIL, "설치",
                "훅 스크립트를 %d/4 개만 찾음 (%s)" % (len(scripts), root),
                "플러그인을 다시 설치할 것",
            )
        )

    # 경로에 공백이 있으면 모델이 만들 명령이 두 조각 난다. 훅은 조용히
    # 성공하므로 밖에서는 "모델이 왜 안 부르지" 로만 보인다.
    if " " in str(root):
        out.append(
            _finding(
                "path_space", WARN, "설치 경로에 공백",
                str(root),
                "규칙의 명령은 따옴표로 감싸져 있어 동작하지만, 직접 칠 때는 따옴표 필요",
            )
        )

    if sys.version_info < (3, 8):
        out.append(
            _finding(
                "python", FAIL, "python3",
                "%d.%d — 3.8 이상 필요" % sys.version_info[:2],
            )
        )
    return out


def check_marketplace():
    """마켓플레이스 사본의 커밋을 보여주고, 설치 캐시가 그 사본과 같은지 대조한다.

    9/3 에 실제로 이것 때문에 "지우고 다시 Install" 이 같은 옛날 커밋을 도로
    가져왔다. 사용자는 재설치를 했다고 믿고 있었다.
    """
    clone = claude_home() / "plugins" / "marketplaces" / "worknav"
    if not (clone / ".git").is_dir():
        return [_finding("marketplace", SKIP, "마켓플레이스", "로컬 클론 없음 (경로 설치)")]
    try:
        head = subprocess.run(
            ["git", "-C", str(clone), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return [_finding("marketplace", SKIP, "마켓플레이스", "git 을 실행할 수 없음")]
    if head.returncode != 0:
        return [_finding("marketplace", SKIP, "마켓플레이스", "커밋을 읽을 수 없음")]

    commit = head.stdout.strip()
    when = subprocess.run(
        ["git", "-C", str(clone), "log", "-1", "--format=%cs"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()

    out = []
    # 원격이 앞서 있는지는 네트워크 없이 알 수 없다. 추측해서 "낡았다" 고
    # 말하지 않는다 — 틀린 표지판은 없는 표지판보다 나쁘다. 날짜는 사실이므로
    # 그것만 보여주고 판단은 사람에게 남긴다.
    out.append(_finding("marketplace", OK, "마켓플레이스", "클론 %s (%s)" % (commit, when)))

    # 대신 네트워크 없이 확실히 아는 것이 하나 있다 — 설치 캐시가 이 클론에서
    # 복사된 게 맞는지. 다르면 Install 을 다른 스냅샷에서 한 것이고,
    # 그 상태로 Uninstall→Install 을 해도 원하는 코드가 안 들어온다.
    installed = plugin_root()
    if ".claude/plugins/cache" in str(installed):
        drift = _src_drift(clone, installed)
        if drift:
            out.append(
                _finding(
                    "cache_drift", FAIL, "설치본이 마켓플레이스 사본과 다름",
                    "다른 파일: %s" % ", ".join(drift[:4]),
                    "Marketplaces → Update 후 Plugins → Uninstall → Install",
                )
            )
    return out


def _src_drift(clone, installed):
    """클론과 설치 캐시의 src/*.py 를 바이트로 대조한다."""
    diff = []
    src = clone / "src"
    if not src.is_dir():
        return diff
    for path in sorted(src.glob("*.py")):
        mirror = installed / "src" / path.name
        try:
            if not mirror.is_file() or mirror.read_bytes() != path.read_bytes():
                diff.append(path.name)
        except OSError:
            diff.append(path.name)
    return diff


def check_enabled():
    path = claude_home() / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [_finding("enabled", SKIP, "설정 파일", "%s 를 읽을 수 없음" % path)]

    plugins = data.get("enabledPlugins")
    on = isinstance(plugins, dict) and any(
        k.startswith("worknav") and v for k, v in plugins.items()
    )
    out = [
        _finding("enabled", OK if on else WARN, "플러그인 활성화",
                 "user scope 에서 켜짐" if on else "~/.claude/settings.json 에 없음",
                 "" if on else "프로젝트 scope 로 설치했다면 정상")
    ]
    if not data.get("statusLine"):
        out.append(
            _finding("statusline", SKIP, "터미널 상태줄", "등록 안 됨",
                     "VS Code 사이드바만 쓰면 필요 없음 (상태바 확장이 대신함)")
        )
    return out


# ---------------------------------------------------------------- 검사 2: 훅


_PAYLOADS = {
    "session_start": {"hook_event_name": "SessionStart", "source": "startup"},
    "on_prompt": {"hook_event_name": "UserPromptSubmit", "prompt": "진단"},
    "on_tool": {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "true"},
        "tool_response": {"stdout": "ok"},
    },
    "on_stop": {"hook_event_name": "Stop"},
}


def check_hooks_fire():
    """훅을 진짜로 돌린다. 임시 프로젝트를 가리키게 해서 부작용을 막는다."""
    scripts = hook_scripts()
    if not scripts:
        return [_finding("hooks", FAIL, "훅", "스크립트를 못 찾음", "플러그인 재설치")]

    out = []
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp)
        (probe / ".git").mkdir()
        _seed_probe_state(probe)

        env = dict(os.environ)
        env["WORKNAV_ROOT"] = str(probe)
        env["CLAUDE_CODE_SESSION_ID"] = "wn-doctor"

        slow, broken = [], []
        for name, path in sorted(scripts.items()):
            payload = dict(_PAYLOADS[name])
            payload.update({"session_id": "wn-doctor", "cwd": str(probe)})
            started = time.monotonic()
            try:
                proc = subprocess.run(
                    [sys.executable, str(path)],
                    input=json.dumps(payload), capture_output=True, text=True,
                    env=env, timeout=HOOK_TIMEOUT_S,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                broken.append("%s (%s)" % (name, exc.__class__.__name__))
                continue
            elapsed = int((time.monotonic() - started) * 1000)
            if proc.returncode != 0 or not _valid_hook_output(proc.stdout):
                broken.append("%s (rc=%d)" % (name, proc.returncode))
            elif elapsed > HOOK_SLOW_MS:
                slow.append("%s %dms" % (name, elapsed))

        if broken:
            out.append(
                _finding("hooks", FAIL, "훅 실행", "실패: %s" % ", ".join(broken),
                         "WORKNAV_HOOK_DEBUG=1 로 다시 돌려 예외를 볼 것")
            )
        elif slow:
            out.append(_finding("hooks", WARN, "훅 실행", "느림: %s" % ", ".join(slow)))
        else:
            out.append(_finding("hooks", OK, "훅 실행", "%d종 정상" % len(scripts)))
    return out


def _seed_probe_state(probe):
    """진단용 임시 프로젝트에 최소 상태를 만든다 — 훅이 침묵하지 않도록."""
    state = store.new_state()
    stamp = store.now_iso()
    state["nodes"]["n0001"] = {
        "title": "진단용 루트", "parent": None, "state": "open",
        "resume_note": None, "origin": None, "opened_at": stamp,
        "closed_at": None, "touched_at": stamp, "session_id": None, "auto": False,
    }
    state["root"] = state["cursor"] = "n0001"
    state["next_id"] = 2
    store.save(state, probe)


def _valid_hook_output(text):
    """빈 출력은 정상이다(침묵). 뭔가 냈다면 우리가 약속한 모양이어야 한다."""
    text = (text or "").strip()
    if not text:
        return True
    try:
        data = json.loads(text)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    return "hookSpecificOutput" in data or "systemMessage" in data


def check_turns(root):
    """등록은 됐는데 한 번도 안 불렸다 — 이게 가장 중요한 신호다.

    훅 실행 검사(위)는 "지금 돌리면 도는가" 만 본다. 실제 세션에서 하네스가
    불러 줬는지는 별개이고, 그건 이 카운터로만 알 수 있다.
    """
    import hooklogic

    if store.load_or_none(root) is None:
        return [
            _finding("turns", SKIP, "주입 기록", "이 프로젝트에서 worknav 를 아직 안 씀",
                     "/wn-root <목표> 로 시작하면 그때부터 쌓임")
        ]

    turns = hooklogic.load_hookstate(root).get("turns")
    total = 0
    sessions = 0
    if isinstance(turns, dict):
        sessions = len(turns)
        for value in turns.values():
            try:
                total += int(value)
            except (TypeError, ValueError):
                continue

    if total:
        return [_finding("turns", OK, "주입 기록", "세션 %d개 · 주입 %d턴" % (sessions, total))]

    # 0턴이라고 다 고장이 아니다. CLI 로만 만들고 아직 훅이 한 번도 안 돈
    # 프로젝트에서는 0이 정상이다. 그걸 문제라고 하면 첫 사용자가 곧바로 틀린
    # 진단을 본다.
    #
    # 판정 근거는 **훅이 직접 쓴 흔적**이어야 한다. events.jsonl 의 session 은
    # 근거가 못 된다 — CLI 를 세션 안의 셸에서 치기만 해도 환경변수가 붙어서
    # 그 필드가 채워지기 때문이다(실제로 이것 때문에 오탐이 났다).
    # hookstate.json 은 훅만 쓴다. 있으면 훅이 돈 것이다.
    if not hooklogic._hookstate_path(root).exists():
        return [
            _finding("turns", SKIP, "주입 기록", "이 프로젝트에서 훅이 아직 돈 적 없음",
                     "세션에서 프롬프트를 한 번 보내면 그때부터 세어짐")
        ]
    return [
        _finding("turns", FAIL, "주입 기록", "훅은 돌았는데 주입 0턴 — 규칙이 안 들어가고 있다",
                 "Developer: Reload Window · 그래도 0이면 설치본이 낡은 것(재설치)")
    ]


# ---------------------------------------------------------------- 검사 3: 상태


def check_state(root):
    out = []
    resolved = store.project_root(str(root))
    is_git = (Path(resolved) / ".git").exists()
    out.append(
        _finding("root", OK if is_git else WARN, "프로젝트 경계",
                 str(resolved) + ("" if is_git else "  (git 저장소 아님)"),
                 "" if is_git else "커맨드와 상태바가 다른 파일을 볼 수 있음")
    )

    path = store.state_path(root)
    if not path.exists():
        out.append(_finding("state", SKIP, "작업 상태", "없음 — 훅은 침묵한다",
                            "/wn-root <목표> 로 시작"))
        return out
    try:
        state = store.load(root)
    except store.StateCorrupt as exc:
        out.append(_finding("state", FAIL, "작업 상태", "손상: %s" % exc,
                            "%s 를 지우고 /wn-root 로 다시 시작" % path))
        return out
    except OSError as exc:
        out.append(_finding("state", FAIL, "작업 상태", "읽기 실패: %s" % exc))
        return out

    config = state.get("config") or {}
    out.append(
        _finding("state", OK, "작업 상태",
                 "d%d · 열린 %d/%d · 보류 %d · 깊이상한 %d"
                 % (store.depth_of(state, state["cursor"]) if state.get("cursor") else 0,
                    render.open_count_excluding_root(state),
                    render.cfg_int(config, "wip_limit", 3),
                    len(store.parked_nodes(state)),
                    render.cfg_int(config, "depth_warn", 3)))
    )
    return out


# ---------------------------------------------------------------- 검사 4: 표지판


def check_signposts(root):
    """표지판이 둘(터미널 파이썬 · 상태바 JS)이라 어긋날 수 있다.

    9/3 에 실제로 .vsix 가 소스보다 낡아서 상태바만 옛날 버전이었다.
    둘이 다른 말을 하기 시작하면 둘 다 못 믿게 된다.
    """
    ext = plugin_root() / "vscode-ext"
    js = ext / "src" / "render.js"
    if not js.is_file():
        return [_finding("signpost", SKIP, "상태바 확장", "소스 없음")]

    out = []
    vsix = sorted(ext.glob("*.vsix"))
    if vsix:
        newest_src = max(p.stat().st_mtime for p in (ext / "src").glob("*.js"))
        if vsix[-1].stat().st_mtime < newest_src:
            out.append(
                _finding("vsix", WARN, "상태바 확장이 소스보다 오래됨", vsix[-1].name,
                         "cd vscode-ext && npx --yes @vscode/vsce package --allow-missing-repository")
            )

    state = store.load_or_none(root)
    if state is None or not shutil.which("node"):
        out.append(_finding("signpost", SKIP, "표지판 일치",
                            "node 없음" if not shutil.which("node") else "비교할 상태 없음"))
        return out

    expected = render.path_line(state, max_width=60, color=False)
    script = (
        "const r=require(%s);"
        "const s=JSON.parse(process.argv[1]);"
        "process.stdout.write(r.pathLine(s,{maxWidth:60})||'');"
    ) % json.dumps(str(js))
    try:
        proc = subprocess.run(
            ["node", "-e", script, json.dumps(state, ensure_ascii=False)],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        out.append(_finding("signpost", SKIP, "표지판 일치", "node 실행 실패"))
        return out

    if proc.returncode != 0:
        out.append(_finding("signpost", SKIP, "표지판 일치", "JS 렌더러를 부를 수 없음"))
    elif proc.stdout == expected:
        out.append(_finding("signpost", OK, "표지판 일치", "터미널 == 상태바"))
    else:
        out.append(
            _finding("signpost", FAIL, "표지판이 서로 다름",
                     "py=%r js=%r" % (expected, proc.stdout),
                     "확장을 다시 빌드하고 설치할 것")
        )
    return out


# ---------------------------------------------------------------- 진입점


def run(root):
    findings = []
    for func in (check_layout, check_marketplace, check_enabled):
        findings += _guard(func)
    findings += _guard(check_hooks_fire)
    for func in (check_turns, check_state, check_signposts):
        findings += _guard(func, root)
    return findings


def _guard(func, *args):
    """진단이 진단 중에 죽으면 안 된다. 어떤 검사가 터져도 나머지는 돈다."""
    try:
        return func(*args)
    except Exception as exc:  # noqa: BLE001 - 진단은 무슨 일이 있어도 끝까지 간다
        return [_finding(getattr(func, "__name__", "?"), WARN, "검사 실패",
                         "%s: %s" % (exc.__class__.__name__, exc))]


def render_report(findings):
    lines = ["worknav doctor", ""]
    for item in findings:
        lines.append("%s %s  %s" % (_SYMBOL.get(item["status"], "?"),
                                    item["title"], item["detail"]))
        if item["action"] and item["status"] in (WARN, FAIL):
            lines.append("    → %s" % item["action"])

    bad = [f for f in findings if f["status"] == FAIL]
    warn = [f for f in findings if f["status"] == WARN]
    lines.append("")
    if bad:
        lines.append("문제 %d개 · 경고 %d개 — 위의 → 를 순서대로 처리할 것"
                     % (len(bad), len(warn)))
    elif warn:
        lines.append("경고 %d개 — 동작에는 지장 없음" % len(warn))
    else:
        lines.append("이상 없음")
    return "\n".join(lines)
