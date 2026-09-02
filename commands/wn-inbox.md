---
description: worknav — 보류함을 보고 오래된 항목을 정리한다
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/wn.py" inbox
```

`[만료]` 표시는 TTL(기본 7일)을 넘긴 항목입니다. **자동으로 폐기하지 마세요.** 만료 항목을 사용자에게 보여주고 폐기할지 물어본 뒤, 승인된 것만 처리하세요.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/wn.py" drop <node-id>
```

지금 할 항목이 있으면 `/wn-resume <node-id>` 입니다.
