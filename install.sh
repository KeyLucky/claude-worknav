#!/usr/bin/env bash
# worknav v0 설치 — 기본은 dry-run. 실제 적용은 --apply 를 명시해야 한다.
#
#   ./install.sh                    무엇이 바뀔지만 출력
#   ./install.sh --apply            스크립트 + 슬래시 커맨드 설치 (settings.json 은 건드리지 않음)
#   ./install.sh --apply --statusline   위 + settings.json 에 statusLine 병합 (백업 후)
set -uo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_SCRIPTS="$HOME/.claude/scripts/worknav"
DEST_COMMANDS="$HOME/.claude/commands"
SETTINGS="$HOME/.claude/settings.json"

APPLY=0
STATUSLINE=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --statusline) STATUSLINE=1 ;;
    *) echo "알 수 없는 인자: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
plan() { if [ "$APPLY" = 1 ]; then say "  [적용] $*"; else say "  [예정] $*"; fi; }

say "worknav v0 설치"
say ""
say "1. CLI 스크립트 → $DEST_SCRIPTS"
for f in store.py render.py wn.py statusline.py; do plan "$f"; done
if [ "$APPLY" = 1 ]; then
  mkdir -p "$DEST_SCRIPTS"
  cp "$SRC_DIR"/src/{store.py,render.py,wn.py,statusline.py} "$DEST_SCRIPTS"/
  chmod +x "$DEST_SCRIPTS"/wn.py "$DEST_SCRIPTS"/statusline.py
fi

say ""
say "2. 슬래시 커맨드 → $DEST_COMMANDS"
for f in "$SRC_DIR"/commands/*.md; do
  name="$(basename "$f")"
  if [ -e "$DEST_COMMANDS/$name" ]; then
    plan "$name  (기존 파일 덮어쐬)"
  else
    plan "$name"
  fi
done
if [ "$APPLY" = 1 ]; then
  mkdir -p "$DEST_COMMANDS"
  # 커맨드 원본은 플러그인 기준으로 ${CLAUDE_PLUGIN_ROOT} 를 쓴다. 홈 복사 설치에는
  # 그 변수가 없으므로 복사하면서 실제 설치 경로로 치환한다.
  for f in "$SRC_DIR"/commands/*.md; do
    sed 's#"${CLAUDE_PLUGIN_ROOT}/src/wn.py"#'"$DEST_SCRIPTS"'/wn.py#g' "$f" \
      > "$DEST_COMMANDS/$(basename "$f")"
  done
fi

say ""
say "3. settings.json statusLine"
if [ "$STATUSLINE" = 1 ]; then
  ARGS=""
  [ "$APPLY" = 1 ] && ARGS="--apply"
  python3 "$SRC_DIR/tools/merge_statusline.py" --settings "$SETTINGS" \
    --command "python3 $DEST_SCRIPTS/statusline.py" $ARGS
else
  say "  [건너뜀] --statusline 을 주지 않았습니다. 상태줄 없이도 슬래시 커맨드는 동작합니다."
fi

say ""
say "4. 훅 (자동 감지·자동 적재)"
say "  [건너뜀] 이 설치 경로는 훅을 등록하지 않습니다."
say "           훅은 남의 settings.json 안으로 병합해야 하는데, 이미 살아 있는"
say "           hooks 블록을 건드릴 위험이 있어 자동화하지 않습니다."
say "           훅까지 쓰려면 플러그인으로 설치하세요:"
say "             /plugin marketplace add KeyLucky/claude-worknav"
say "             /plugin install worknav@worknav"

say ""
if [ "$APPLY" = 1 ]; then
  say "설치 완료. 새 세션에서 /wn-root <목표> 로 시작하세요."
else
  say "dry-run 이었습니다. 실제로 적용하려면 --apply 를 붙이세요."
fi
