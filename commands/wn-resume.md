---
description: worknav — 보류 항목을 꺼내 지금 작업으로 삼는다
---

`$ARGUMENTS` 의 노드를 열고 커서를 그리로 옮깁니다. 현재 노드가 열려 있으면 복귀지점을 먼저 적습니다 (`/wn-push` 와 같은 이유).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/wn.py" resume <node-id> --resume-note "<현재 노드의 복귀지점>"
```

node-id 를 모르면 `/wn-inbox` 를 먼저 보여주고 고르게 하세요.
