# worknav — 작업 길잡이 (v0.5)

작업 도중 의문과 부가작업이 가지치기로 늘어나 원래 목표를 잃는 문제를 다룬다.

핵심은 기록이 아니라 **기본값**이다. 새로 생긴 가지는 기본적으로 보류(PARK)하고, 정말 지금 막고 있을 때만 내려간다(PUSH). 되돌아올 때는 떠날 때 적어둔 한 문장을 그대로 돌려준다(POP).

- 설계 근거와 자료구조: [DESIGN.md](./DESIGN.md)
- 단계별 계획과 인수 조건: [PLAN.md](./PLAN.md)

## 현재 상태

v0.5 = 수동 슬래시 커맨드 + 표지판 + **훅 자동화**.
인수 테스트 87개 통과 (본체) + 26개 (VS Code 확장).

```
src/store.py       스키마, 파일 잠금, 원자적 교체
src/render.py      경로 한 줄 / 트리 / 보류함
src/wn.py          CLI — 상태 변경의 유일한 진입점
src/statusline.py  읽기 전용 상태줄
src/detect.py      가지 후보 감지 (정규식만, LLM 아님)
src/hookrt.py      훅 stdin/stdout 계약, 출력 예산, fail-safe
src/hooklogic.py   훅 4종의 로직 (순수 함수라 단위 테스트된다)
hooks/             훅 정의 + 진입점 4개
commands/          슬래시 커맨드 8개
tools/             settings.json 병합기 (기존 키 보존)
tests/             인수 테스트 T1~T14 (기능), W1~W7 (이식성), 훅 42개
vscode-ext/        VS Code 상태 표시줄 확장 (별도 설치)
```

### 훅이 자동으로 하는 일

플러그인으로 설치하면 다음이 저절로 돈다. 명령을 안 쳐도 된다.

| 시점 | 하는 일 |
|---|---|
| 세션 시작 | 현재 경로와 복귀지점, 보류함 개수를 되살려 준다 |
| 프롬프트마다 | 현재 경로를 한 줄 주입. 오래 열린 노드가 있으면 POP 을 상기시킨다 |
| 툴 실행 후 | 에러·경고·`TODO` 를 보류함에 **자동으로 담고** 한 줄 알린다 |
| 세션 종료 | 열린 노드·보류함·깊이 게이트 횟수 요약 |

**자동으로 하지 않는 것이 더 중요하다.** PUSH(가지로 내려가기)는 어떤 경우에도
자동화하지 않는다. 담기(PARK)는 틀려도 쓸모없는 한 줄이 늘고 끝나지만, 내려가기는
한 번 잘못 판단하면 사람을 엉뚱한 곳으로 끌고 가고 그러면 도구 자체를 못 믿게 된다.

훅은 **옵트인**이다. `/wn-root` 를 한 번도 안 한 프로젝트에서는 아무 말도 하지 않는다.

무언가 잘못 도는 것 같으면 진단 스위치를 켠다. 평소에는 훅이 어떤 오류도 삼키기 때문에
증상이 "아무것도 안 뜬다" 로만 보인다.

```bash
WORKNAV_HOOK_DEBUG=1 python3 hooks/on_tool.py < 페이로드.json
```

## 테스트

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

의존성 없음. `python3 -S` 로도 돈다.

## 요구사항

- **Python 3.8+** 만 있으면 된다. 외부 패키지 없음
- **Windows / macOS / Linux** 전부 동작한다. 파일 잠금은 POSIX 에서 `fcntl.flock`,
  Windows 에서 `msvcrt.locking` 을 쓴다 (둘 다 프로세스가 죽으면 OS 가 자동으로 푼다)
- 표지판을 VS Code 상태 표시줄에 띄우려면 VS Code 1.75+ (`vscode-ext/`)

## 설치

리포를 그대로 마켓플레이스로 쓴다 (`.claude-plugin/marketplace.json`). 세 갈래 다 결과가 같고
커맨드 8개가 동일하게 동작한다.

### 1. GitHub 에서 (다른 환경 배포용)

```
/plugin marketplace add KeyLucky/claude-worknav
/plugin install worknav@worknav
```

Claude Code VS Code 확장을 쓰면 터미널이 필요 없다 — `Manage Plugins` → `Marketplaces` 탭에
`KeyLucky/claude-worknav` 를 넣고 Add, 그다음 `worknav` 를 Install. Windows 에서도 같다.

### 2. 로컬 폴더에서

리포를 내려받았다면 GitHub 없이 절대 경로만으로 설치된다 (`source: "directory"`).

```bash
claude plugin marketplace add /절대/경로/worknav
claude plugin install worknav@worknav
```

같은 값을 위의 Marketplaces 탭 path 칸에 넣어도 된다.

커맨드는 `${CLAUDE_PLUGIN_ROOT}/src/wn.py` 를 부르므로 두 방법 모두 경로 설정이 필요 없다.

### 3. 홈 디렉터리 복사

플러그인 구조를 쓰지 않는 환경용. 기본은 dry-run이라 무엇이 바뀌는지 먼저 보고 결정한다.

```bash
./install.sh                          # 계획만 출력
./install.sh --apply                  # 스크립트 + 슬래시 커맨드 설치
./install.sh --apply --statusline     # 위 + settings.json 에 statusLine 병합 (백업 후)
```

복사할 때 커맨드 안의 `${CLAUDE_PLUGIN_ROOT}/src/wn.py` 를 실제 설치 경로로 치환한다.
`install.sh` 는 bash 스크립트라 **Windows 에서는 쓸 수 없다.** Windows 에서는 1번이나 2번을 쓴다.

**이 방법으로는 훅이 설치되지 않는다.** 훅은 `settings.json` 의 `hooks` 블록에 병합해야
하는데, 이미 살아 있는 훅 설정을 건드릴 위험이 있어 자동화하지 않았다. 자동 감지까지
쓰려면 1번이나 2번(플러그인)으로 설치한다.

### VS Code 상태 표시줄 확장 (선택)

사이드바 채팅 UI 로 작업하면 터미널 상태줄이 보이지 않는다 (DESIGN §5.4). 같은 표지판을
에디터 상태 표시줄에 띄우려면 이 확장을 따로 설치한다. Claude Code 플러그인이 아니라
VS Code 확장이라 설치 경로가 다르다.

설치 파일(`.vsix`)은 리포에 두지 않는다. 직접 만든다 — Node 만 있으면 되고 외부 의존성은 없다.

```bash
cd vscode-ext
npm test                                        # 26개 통과 확인
npx --yes @vscode/vsce package --allow-missing-repository
```

그다음 확장 뷰(Ctrl+Shift+X) → 우측 상단 `...` → `Install from VSIX...` → 만들어진 `.vsix` 선택.

`--statusline` 은 `~/.claude/settings.json` 을 건드린다. 병합기는 기존 키를 전부 보존하고, 적용 전에 타임스탬프 백업을 남기며, `statusLine` 이 이미 있으면 `--replace` 없이는 손대지 않는다.

**VS Code 사이드바(웹뷰)로 작업한다면 `--statusline` 은 의미가 없다.** 터미널 상태줄은 웹뷰에 그려지지 않는다. 대신 `vscode-ext/` 의 VS Code 확장을 설치하면 같은 표지판이 에디터 상태 표시줄에 뜬다 (DESIGN §5.4).

## 쓰는 법

```
/wn-root  논문 실험 파트 재현     이번 작업의 목표를 한 줄로
/wn-park  numpy 버전 경고         새 가지를 보류함에 담고 하던 일 계속
/wn-push  seed 고정               지금 막고 있을 때만 내려감 (복귀지점 필수)
/wn-pop                           끝내고 복귀 — 떠날 때 적은 문장을 돌려받음
/wn-where /wn-tree /wn-inbox      현재 위치 / 전체 트리 / 보류함
```

상태줄은 이렇게 보인다. 왼쪽이 출발지, 오른쪽 끝이 현위치, `d2` 가 깊이, `⑂9` 가 보류함 개수.

```
⟩ 논문 실험 파트 재현 › ablation S_… › seed 고정  d2  ⑂9
```

## 상태 파일

프로젝트(git root)의 `.claude/worknav/` 아래.

- `state.json` — 단일 진실원
- `events.jsonl` — append-only 이벤트 로그. 사용 데이터를 여기서 걷는다.
  자동 적재는 `result: "auto"` 로 남으므로 나중에 오탐률을 실측할 수 있다
- `hookstate.json` — 훅의 알림 억제 캐시. 진실원이 아니라서 지워도 무해하다
- `archive/` — `root --force` 로 밀려난 이전 트리

커밋하고 싶지 않으면 `.gitignore` 에 `/.claude/worknav/` 를 넣는다. 도구는 관여하지 않는다.
