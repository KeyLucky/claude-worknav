#!/usr/bin/env python3
"""worknav PostToolUse 훅 — 진입점. 로직은 src/hooklogic.py 에 있다.

이 파일은 얇게 유지한다. 훅은 매 툴 호출마다 도는 경로라
여기서 무거운 일을 하면 작업 속도가 체감된다.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# 플러그인 배치(hooks/ 와 src/ 가 형제)와 install.sh 배치(한 폴더에 평평하게)를
# 둘 다 지원한다. 어느 쪽이든 import 가 되는 경로가 하나는 들어간다.
for _cand in (os.path.join(os.path.dirname(_HERE), "src"), _HERE):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)

try:
    import hooklogic
    import hookrt
except Exception:  # 길잡이가 작업을 막으면 안 된다
    sys.exit(0)

if __name__ == "__main__":
    sys.exit(hookrt.run(hooklogic.on_tool, "PostToolUse"))
