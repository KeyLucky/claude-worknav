---
description: worknav — 보류 항목을 꺼내 지금 작업으로 삼는다
---

`$ARGUMENTS` 의 노드를 열고 커서를 그리로 옮깁니다. 현재 노드가 열려 있으면 복귀지점을 먼저 적습니다 (`/wn-push` 와 같은 이유).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/wn.py" resume <node-id> --resume-note "<현재 노드의 복귀지점>"
```

node-id 를 모르면 `/wn-inbox` 를 먼저 보여주고 고르게 하세요.

**resume 도 노드를 하나 여는 행위라 WIP 게이트에 걸립니다.** 종료 코드 3 이 나오면 `/wn-push` 와 똑같이 게이트 문구를 그대로 보여주고 멈추세요. 스스로 `--force` 를 붙이지 마세요 — 보류함에서 꺼내는 것으로 상한을 우회하면 상한을 둔 의미가 없어집니다.
