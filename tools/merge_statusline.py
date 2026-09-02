#!/usr/bin/env python3
"""settings.json 에 statusLine 을 병합한다. 통째 교체하지 않는다.

이 파일에는 이미 hooks / enabledPlugins / extraKnownMarketplaces 등 살아 있는
설정이 들어 있다. 전체를 새로 쓰면 그것들이 날아간다. 그래서:
  - 기존 JSON 을 읽어 키 하나만 추가하고
  - 적용 전에 타임스탬프 백업을 남기고
  - statusLine 이 이미 있으면 --replace 없이는 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace", action="store_true", help="기존 statusLine 을 덮어씌")
    args = parser.parse_args(argv)

    path = Path(os.path.expanduser(args.settings))
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print("  [중단] settings.json 이 올바른 JSON 이 아닙니다: %s" % exc)
            print("  손상된 파일은 건드리지 않습니다. 먼저 직접 고치세요.")
            return 1
        if not isinstance(settings, dict):
            print("  [중단] settings.json 최상위가 객체가 아닙니다.")
            return 1
    else:
        settings = {}

    existing = settings.get("statusLine")
    if existing and not args.replace:
        print("  [건너뜀] statusLine 이 이미 있습니다:")
        print("           %s" % json.dumps(existing, ensure_ascii=False))
        print("           덮어쓰려면 --replace 를 주세요.")
        return 0

    preserved = sorted(k for k in settings if k != "statusLine")
    print("  [보존] %s" % (", ".join(preserved) if preserved else "(없음)"))
    print("  [추가] statusLine.command = %s" % args.command)

    if not args.apply:
        print("  [예정] 아직 쓰지 않았습니다 (--apply 필요)")
        return 0

    if path.exists():
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name("settings.json.bak-%s" % stamp)
        shutil.copy2(path, backup)
        print("  [백업] %s" % backup)

    settings["statusLine"] = {"type": "command", "command": args.command, "padding": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("settings.json.tmp.%d" % os.getpid())
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    print("  [적용] %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
