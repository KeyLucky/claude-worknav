#!/usr/bin/env python3
"""가지 후보 감지 — 정규식만. LLM 을 부르지 않는다.

매 툴 호출마다 도는 경로다. LLM 분류는 느리고 비싸며, v0.5 의 목적은
감지 정밀도가 아니라 자동 적재가 실제로 쓸 만한지를 재는 것이다.
오탐률(T13)을 실측한 뒤에 임계를 조정한다.

설계 원칙: 오탐이면 보류함에 쓰레기 한 줄이 늘고 끝난다. 미탐이면 현상 유지다.
둘 다 싸다. 그래서 감지는 공격적이어도 되지만, PUSH 는 어떤 경우에도 하지 않는다.
"""

from __future__ import annotations

import re

# 제목으로 쓸 최대 길이. 보류함은 훑어보는 목록이라 길면 안 읽는다.
TITLE_MAX = 60

# 감지 규칙. (이름, 정규식, 우선순위) — 우선순위가 낮을수록 먼저 채택된다.
#
# `\bError\b` 로 쓰면 안 된다. 파이썬 예외는 거의 전부 `ValueError`, `KeyError`
# 처럼 앞에 글자가 붙어 있어서 단어 경계가 성립하지 않는다. 스모크에서 실제로
# `ValueError: seed must be int` 를 통째로 놓쳤다.
_ERROR_WORD = r"(?:\w*Error|ERROR|FATAL|[Ee]xception|[Ff]ail(?:ed|ure|s)?|error)\b"
_WARN_WORD = r"(?:[Ww]arning|WARN|Deprecat\w*)\b"

_RULES = (
    ("traceback", re.compile(r"^\s*Traceback \(most recent call last\)", re.M), 0),
    ("error", re.compile(r"^[^\n]{0,120}?" + _ERROR_WORD + r"[^\n]*", re.M), 1),
    ("warning", re.compile(r"^[^\n]{0,120}?" + _WARN_WORD + r"[^\n]*", re.M), 2),
)

_TODO = re.compile(r"(?:#|//|/\*|<!--)?\s*(TODO|FIXME|XXX|HACK)\b[:\s]*([^\n]*)")

# 이 문자열이 명령에 있으면 감지 자체를 건너뛴다.
# worknav 자기 출력(게이트 문구, 트리)에는 '⚠' 나 park 목록이 들어 있어서
# 자기가 만든 출력을 다시 가지로 잡는 되먹임이 생긴다.
_SELF_MARKERS = ("wn.py", "worknav", "/wn-")

# 검사 자체가 목적인 명령. 여기서 나온 error/warning 은 이미 사람이 보고 있다.
_INSPECTION = re.compile(r"\b(?:grep|rg|ag|ack|find|cat|head|tail|less|git\s+log|git\s+diff)\b")

# 도구가 스스로 만든 잡음. 실제 작업과 무관하다.
_NOISE = re.compile(
    r"(?:"
    r"npm\s+(?:WARN|notice)"
    r"|error(?:s)?\s*[:=]\s*(?:0|\[\]|null|none)\b"
    r"|0\s+errors?\b"
    r"|no\s+errors?\s+found"
    r"|--?[a-z-]*error"          # --error-format 같은 플래그
    r"|\berror_?(?:code|count|handler|message|type)\b"
    r")",
    re.I,
)


def _clean(line):
    """제목으로 쓸 수 있게 다듬는다. ANSI 와 앞머리 경로를 걷어낸다."""
    line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
    line = line.strip().strip("|").strip()
    line = re.sub(r"\s+", " ", line)
    if len(line) > TITLE_MAX:
        line = line[: TITLE_MAX - 1] + "…"
    return line


def normalize(title):
    """중복 판정용 키. 숫자·경로·따옴표 안 내용이 달라도 같은 가지로 본다.

    같은 에러가 툴 호출마다 다시 잡히면 보류함이 그 한 줄로 가득 찬다.
    이걸 막는 게 자동 적재를 쓸 만하게 만드는 유일한 장치다.
    """
    text = (title or "").lower()
    text = re.sub(r"['\"`][^'\"`]*['\"`]", " ", text)   # 따옴표 안은 매번 다르다
    text = re.sub(r"(?:/[\w.\-]+)+", " ", text)          # 경로
    text = re.sub(r"\b\d+\b", " ", text)                 # 줄 번호, 카운트
    text = re.sub(r"[^\w가-힣]+", " ", text)
    return " ".join(text.split())[:80]


def _tool_text(tool_name, tool_input, tool_response):
    """감지 대상 텍스트. 툴마다, 그리고 성공/실패마다 내용이 있는 자리가 다르다.

    실패한 툴은 PostToolUse 가 아니라 PostToolUseFailure 로 오고, 내용이
    tool_response 가 아니라 최상위 `error` 문자열에 들어온다. 종단 검증에서
    실패한 명령이 통째로 안 잡히는 걸 보고서야 발견했다 — 가지의 주요 원천이
    바로 그 실패한 명령이다.
    """
    tool_input = tool_input or {}
    tool_response = tool_response or {}
    if isinstance(tool_response, str):
        return tool_response
    if tool_name == "Bash":
        parts = [tool_response.get("stdout") or "", tool_response.get("stderr") or ""]
        return "\n".join(p for p in parts if p)
    # Edit / Write 는 응답이 아니라 사람이 새로 써 넣은 내용에서 찾는다.
    for key in ("new_string", "content"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _skip_reason(tool_name, tool_input, tool_response):
    tool_input = tool_input or {}
    command = tool_input.get("command") or ""
    haystack = command + " " + str(tool_input.get("file_path") or "")
    if any(marker in haystack for marker in _SELF_MARKERS):
        return "self"
    if tool_name == "Bash":
        if _INSPECTION.search(command):
            return "inspection"
        # tool_response 는 dict(PostToolUse) 이거나 문자열(PostToolUseFailure 의 error) 이다.
        # 문자열에 .get 을 부르면 예외가 나는데, 훅의 fail-safe 가 그걸 삼켜서
        # 밖에서는 "아무것도 안 담긴다" 로만 보인다. 실제로 그렇게 놓쳤다.
        if isinstance(tool_response, dict) and tool_response.get("interrupted"):
            return "interrupted"
    return None


def detect(tool_name, tool_input, tool_response):
    """가지 후보 하나를 고른다. 없으면 None.

    한 번의 툴 호출에서 여러 개를 담지 않는다 — 에러 하나가 수십 줄로 번지는 게
    보통이고, 그걸 다 담으면 보류함이 그 한 사건으로 가득 찬다.
    """
    if _skip_reason(tool_name, tool_input, tool_response):
        return None

    text = _tool_text(tool_name, tool_input, tool_response)
    if not text:
        return None

    # TODO/FIXME 는 사람이 직접 적어 넣은 것이라 신호가 가장 강하다.
    if tool_name in ("Edit", "Write", "MultiEdit"):
        found = _TODO.search(text)
        if found:
            tag, rest = found.group(1), found.group(2).strip()
            title = _clean("%s: %s" % (tag, rest) if rest else tag)
            return {"title": title, "kind": "todo"}
        return None

    best = None
    for kind, pattern, priority in _RULES:
        match = pattern.search(text)
        if not match:
            continue
        line = _clean(_traceback_tail(text) if kind == "traceback" else match.group(0))
        if not line or _NOISE.search(line):
            continue
        if best is None or priority < best[0]:
            best = (priority, {"title": line, "kind": kind})
    return best[1] if best else None


def _traceback_tail(text):
    """트레이스백은 첫 줄이 아니라 마지막 줄이 내용이다.

    "Traceback (most recent call last)" 를 제목으로 담으면 보류함에서
    어떤 사건이었는지 알아볼 수 없다.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for line in reversed(lines):
        if line.startswith((" ", "\t")):
            continue  # 스택 프레임 줄
        if line.lstrip().startswith("Traceback"):
            break
        return line
    return lines[-1] if lines else ""
