# worknav — 구현 계획

설계서: [DESIGN.md](./DESIGN.md)

## 원칙

**v0는 리포를 만들지 않는다.** 지금 이 스택 모델이 실제 작업 패턴에 맞는지 모른다. 리포부터 파고 버전을 붙이면 틀렸을 때 버리기가 어려워진다. 2주 쓰고 §미해결 질문(DESIGN §7)에 답이 나온 뒤에 리포로 승격한다.

각 마일스톤은 **그 자체로 쓸모가 있어야 한다.** 다음 단계가 없어도 손해가 아니어야 한다.

---

## v0 — 수동 스택 (목표: 반나절 구현, 2주 사용)

리포 없음. `~/.claude/` 에 직접 둔다.

```
~/.claude/
  scripts/worknav/
    wn.py            # CLI 단일 진입점 (root/push/pop/park/where/tree/inbox/resume)
    store.py         # state.json 읽기·쓰기, 파일 잠금, 원자적 교체
    render.py        # 경로 한 줄 / 트리 / 보류함 렌더
    statusline.py    # 읽기 전용 상태줄
  commands/
    root.md push.md pop.md park.md where.md tree.md inbox.md resume.md
  settings.json      # statusLine 등록 (기존 hooks 보존, 병합)
```

이 단계에 **훅은 없다.** 전부 사람이 슬래시 커맨드로 친다.

이유: 자동 감지를 먼저 만들면 감지가 정확한지, 애초에 스택 모델이 맞는지 모르는 채로 훅을 디버깅하게 된다. 수동으로 2주 쓰면 `depth_warn`, `stale_open_min`, PARK 기본값이 맞는지가 데이터로 나온다.

단, **상태줄은 v0에 넣는다.** 상시 노출이 이 도구 가치의 절반이고, 읽기 전용이라 위험이 없다.

### 구현 순서

1. `store.py` — 스키마 + 파일 잠금 + 원자적 교체. 여기가 틀리면 나머지가 전부 무의미하다.
2. `wn.py root/push/pop/park` — 4개 연산.
3. `render.py` + `statusline.py` — 표시.
4. `wn.py where/tree/inbox/resume` — 조회.
5. `commands/*.md` — 슬래시 커맨드 8개.
6. `settings.json` 에 `statusLine` **병합** (기존 `hooks` 블록 훼손 금지 — 현재 `PreToolUse:Agent`, `UserPromptSubmit` 두 개가 살아 있다).

### v0 인수 조건

전부 자동 테스트로 확인 가능해야 한다.

- **T1 왕복** — `root → push A → push B → pop → pop` 후 커서가 루트, A·B는 `done`, POP마다 부모의 `resume_note` 가 정확히 출력됨
- **T2 깊이 게이트** — 깊이 3 `push` 는 `--force` 없이 exit 3, 상태 파일 변경 없음
- **T3 복귀지점 강제** — `resume_note` 없이 `push` 시 exit 2, 상태 변경 없음
- **T4 PARK 커서 불변** — `park` 후 커서 id가 이전과 동일
- **T5 TTL** — 8일 지난 `parked` 노드가 `/inbox` 에서 만료 표시됨. 자동 삭제 안 됨
- **T6 상태줄 무결성** — `state.json` 없음 / 빈 파일 / 깨진 JSON 세 경우 모두 빈 출력 + exit 0
- **T7 동시성** — 두 프로세스가 동시에 `park` 100회씩 → 노드 200개, id 중복 없음, 유실 없음
- **T8 깊이 파생** — `parent` 체인이 5단계일 때 `where` 의 깊이가 5. 어디에도 `depth` 필드가 저장되지 않음

### v0 사용 기간에 수집할 것

`wn.py` 가 `.claude/worknav/events.jsonl` 에 append-only로 남긴다.

- 게이트 발동 횟수 / 그중 `--force` 통과 비율 → `depth_warn` 조정 근거
- park된 항목 중 실제로 `resume` 된 비율 → 보류함이 쓰레기통인지 판정
- POP 시점의 노드 체류 시간 분포 → `stale_open_min` 조정 근거
- 최대 도달 깊이 분포

---

## v0.5 — 훅 자동화 (전제: v0 2주 사용 후 DESIGN §7 중 최소 3개에 답이 나왔을 때)

개인 GitHub 리포로 옮기고 `.claude-plugin/plugin.json` 을 붙인다. 본인만 설치.

추가하는 것:

- `hooks/hooks.json` + 훅 4종 (DESIGN §4)
- `on_tool.py` 의 **정규식 가지 감지** (LLM 아님)
- `SessionStart` 복귀 배너
- `UserPromptSubmit` 의 stale open 노드 POP 확인

### v0.5 인수 조건

- **T9 fail-safe** — 훅 스크립트에 강제로 예외를 심어도 세션이 정상 진행되고 stderr가 새지 않음
- **T10 예산** — UserPromptSubmit 주입 ≤ 400자, PostToolUse 출력 ≤ 1줄 80자
- **T11 무의존** — `python3 -S` 로 실행해도 동작 (표준 라이브러리만)
- **T12 지연** — `on_tool.py` p95 < 200ms (툴 호출마다 도는 경로)
- **T13 오탐률** — 실제 세션 로그 50건에서 감지된 가지 중 사람이 "쓰레기"로 판정한 비율 측정. 40% 넘으면 감지 임계를 올린다

---

## v1 — 배포 (전제: v0.5를 2주 쓰고 T13이 통과했을 때)

- `.claude-plugin/marketplace.json` 추가 → 남이 설치 가능
- README, 설정 옵션 문서화 (`depth_warn` 등을 사용자가 조정 가능하게)
- OpenClaw 2차 진입점 — Slack에서 "이거 보류함" 한 줄이 같은 `state.json` 에 들어가게. 스키마 소유권은 플러그인, OpenClaw는 얇은 write 클라이언트

v1에서 처음으로 "남이 쓸 때 어떤가"를 고민한다. 그 전까지는 1인 도구로 만든다.

---

## v0-deploy — GitHub 배포 (완료)

`KeyLucky/claude-worknav` (public). 리포 자체가 마켓플레이스다.

```
/plugin marketplace add KeyLucky/claude-worknav
/plugin install worknav@worknav
```

격리 환경(`CLAUDE_CONFIG_DIR`)에서 확인한 것.

- GitHub 소스로 `marketplace add` → `plugin install` → 커맨드 8개 인식
- 설치된 캐시 경로에서 `root` → `push` → `park` → `path` → `tree` 실제 실행
- **SSH 키가 없어도 된다.** CLI 가 먼저 `git@github.com:` 으로 시도하고 실패하면
  `https://` 로 자동 폴백한다. `GIT_SSH_COMMAND=/bin/false` 로 막아 확인했다 —
  Windows 사용자 대부분이 이 경로를 탄다
- clone 후 `npm test` 26개 통과, `vsce package` 로 `.vsix` 생성까지

파일은 GitHub API 로 올렸다. **옮기는 과정에서 한글 세 글자가 깨졌다** (`끊긴`→`끕긴`,
`뭘`→`뭔`, `덮어씀`→`덮어씌`). 전부 주석과 안내 문구라 동작에는 영향이 없었지만, 코드
로직이었다면 조용히 깨졌을 자리다. clone 후 로컬과 `diff` 로 전수 대조해서 잡았다.
**전송 후 대조는 생략하면 안 된다.**

`.vsix` 는 리포에 두지 않는다. 바이너리라 API 로 못 올리고, 무엇보다 소스에서 언제든
다시 만들 수 있다. README 에 빌드 두 줄을 적어 뒀다.

---

## v0-portable — Windows 포함 이식성 (완료)

다른 환경에 배포하려면 POSIX 가정을 걷어내야 했다. `install.sh` 로 자기 머신에만 깔 때는
드러나지 않던 것들이다. 셋 다 **Windows 에서 조용히 실패하는** 종류였다.

| 지점 | 증상 | 대응 |
|---|---|---|
| `import fcntl` | Windows 에 없음 → 모듈 import 자체가 실패 | `fcntl` / `msvcrt` 를 선택적으로 import 하고 `_try_lock` / `_unlock` 으로 감쌈 |
| `select.select(sys.stdin)` | Windows 의 select 는 소켓만 받음 → 예외 | 데몬 스레드 + `join(timeout)` 으로 교체. 플랫폼 분기가 사라짐 |
| 콘솔 인코딩 | cp949 에서 `⟩ › ⑂` 가 `UnicodeEncodeError`, statusline 의 except 가 삼켜서 **빈 줄** | `force_utf8_output()` 으로 stdout/stderr 재구성 |

세 번째가 가장 나빴다. 예외가 밖으로 안 나오고 표지판만 사라지므로, 사용자 입장에서는
"설치했는데 아무것도 안 뜬다"가 된다. 원인을 짚을 단서가 없다.

`os.replace` 도 손봤다. POSIX 는 읽는 중인 파일을 교체해도 성공하지만 Windows 는
`PermissionError` 를 낸다. 표시 쪽이 파일을 여는 시간은 밀리초라 짧게 재시도한다.

인수 조건 W1~W7 (`tests/test_portability.py`). POSIX 전용 모듈을 강제로 없는 것처럼 만들어
같은 코드 경로를 통과시킨다.

- W1 잠금 수단이 아예 없어도 상태는 저장된다 (길잡이가 작업을 막으면 안 된다)
- W2 `fcntl` 이 없으면 msvcrt 경로로 넘어간다 — 잠금/해제 구간이 같은지까지 확인
- W3 잠금이 잡혀 있으면 어느 플랫폼이든 매달리지 않고 exit 5
- W4 `replace` 가 두 번 실패해도 재시도로 성공한다
- W5 `PYTHONIOENCODING=cp949` 하위 프로세스에서 표지판이 정상 출력된다
- W6 `force_utf8_output` 은 어떤 스트림에서도 예외를 내지 않는다
- W7 stdin 이 비어 있어도 상태줄이 매달리지 않는다

W5 는 수정을 되돌려 실패하는 것까지 확인했다 (되돌리면 stdout 이 빈 문자열).

**여기서 증명되지 않는 것** — msvcrt 잠금이 실제 Windows 에서 배타성을 갖는지. 그건 Windows 에서
T7(두 프로세스 동시 park)을 돌려야만 안다. 세션 하나로 쓰는 한 문제되지 않는다.

---

## v0-plugin — 플러그인 구조 전환 (완료)

v1 로 미뤄뒀던 것을 앞당겼다. 이유는 하나 — Claude Code VS Code 확장 환경에서는 터미널의
`claude` 명령을 못 쓰는 경우가 있고, 확장 UI 의 Manage Plugins → Marketplaces 가 사실상
유일한 설치 경로다. `install.sh` 는 그 경로로 쓸 수 없다.

바이너리에서 확인한 마켓플레이스 소스 종류: `github` / `url` / `npm` / `git-subdir` /
`file` / `directory`. **`directory` 가 로컬 폴더를 그대로 받는다** — 리포를 GitHub 에
올리지 않아도 절대 경로만으로 설치된다.

한 작업만 필요했다.

- 커맨드 8개의 `python3 ~/.claude/scripts/worknav/wn.py` → `python3 "${CLAUDE_PLUGIN_ROOT}/src/wn.py"`
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` 추가 (`source: "./"`)
- `install.sh` 는 복사 시 그 변수를 실제 경로로 치환하도록 수정 — 두 설치 방법이 공존한다

격리 검증 (`CLAUDE_CONFIG_DIR=/tmp/...` 로 실제 `~/.claude` 를 건드리지 않고).

- `claude plugin validate` — 매니페스트 2개 통과
- `marketplace add <로컬 절대경로>` → `plugin install worknav@worknav` 성공
- `plugin details worknav` — 커맨드 8개 전부 인식, always-on 약 94토큰
- 설치된 캐시 경로(`plugins/cache/worknav/worknav/0.1.0/src/wn.py`)에서 `root` → `push` →
  `park` → `path` 를 실제로 돌려 표지판 문자열까지 확인

부수 효과 하나 — 플러그인 설치 시 리포 전체가 복사되므로 `vscode-ext/*.vsix` 도 캐시에 함께 들어간다.

---

## v0-vscode — VS Code 상태 표시줄 (완료, `vscode-ext/`)

v0.5보다 먼저 만들었다. 순서를 앞당긴 이유는 하나다 — 주 작업 환경이 Claude Code VS Code 확장의
사이드바 채팅 UI인데, 거기서는 터미널 상태줄이 원리적으로 보이지 않는다 (DESIGN §5.4). 표지판이
안 보이면 v0를 2주 써볼 수도 없다.

구성물은 셋. 외부 의존성 없음.

- `src/render.js` — `render.py` 의 이식본 (`path_line` / `tree` / `inbox` / `tooltip`)
- `src/locate.js` — `store.project_root` 와 같은 git 루트 탐색
- `extension.js` — 상태 표시줄 항목, 파일 변경 감시, 명령 3개

인수 조건 26개 통과 (`npm test`). 나눠 보면 이렇다.

- **X1–X2 크로스 체크** — 같은 상태에서 파이썬 렌더러와 JS 렌더러의 출력이 문자 단위로 일치.
  이게 이 확장에서 가장 중요한 테스트다. 표지판 두 개가 다른 말을 하면 둘 다 못 믿게 된다
- **E1–E9 종단** — 실제 `wn.py` 를 돌려 만든 상태 파일로 확장을 구동한다. 합성 픽스처만 쓰면
  CLI 가 실제로 쓰는 스키마와 어긋나도 통과하므로, 여기서는 CLI 를 그대로 부른다
- **R1–R12 / L1–L3** — 깨진 입력, 폭 압축 종료, parent 순환, git 루트 경계

육안 확인에서 잡은 것 (테스트만으로는 안 나왔다).

- `package.json` 의 `test` 스크립트가 `node --test test/` 라 실행 자체가 실패했다
- `alignment` 설정을 바꿔도 반영되지 않았다 (항목 생성 시점에만 읽음) → 재생성하도록 수정
- 노드 제목에 `$(` 가 들어가면 VS Code 가 아이콘 문법으로 해석해 표지판 한가운데가 사라진다
  → 상태 표시줄로 나갈 때만 끊는 후처리 추가
- 좁은 폭에서 압축이 예산을 못 지키는 하한이 존재한다. 이건 버그가 아니라 "루트와 현재는
  버리지 않는다"의 대가다. 테스트로 고정하고 README 에 명시했다

`npx @vscode/vsce package` 로 `.vsix` 생성까지 확인했다 (12KB, 테스트 파일 제외).

---

## 하지 않기로 한 것

기록해 둔다. 나중에 "이거 왜 없지" 할 때 다시 논의하지 않기 위해서.

- **자동 PUSH** — 오탐 한 번의 비용이 너무 크다 (DESIGN §4.2)
- **작업 중 전체 트리 표시** — 눈이 형제 노드로 가서 가지치기를 부추긴다 (DESIGN §2)
- **v0의 LLM 분류** — 느리고 비싸고, v0의 목적이 아니다 (DESIGN §4.1)
- **세션별 커서** — 실제로 동시 세션을 그렇게 쓰는지 모른다. 문제가 생기면 그때 (DESIGN §2.2)
- **일정 추정 / 티켓 연동** — 비목표 (DESIGN §0)
