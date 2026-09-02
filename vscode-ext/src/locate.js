'use strict';
/**
 * 상태 파일 찾기 — store.py 의 project_root 와 같은 규칙.
 *
 * 프로젝트 경계는 git 루트다. cwd 기준으로만 잡으면 하위 디렉터리를 열었을 때
 * 상태가 갈라진다. 여기서 규칙이 어긋나면 다른 프로젝트의 표지판을 띄우게 된다.
 */

const fs = require('fs');
const path = require('path');

const STATE_REL = path.join('.claude', 'worknav', 'state.json');

/** start 에서 위로 올라가며 .git 을 찾는다. 없으면 start 자신. */
function projectRoot(start, exists) {
  const stat = exists || ((p) => fs.existsSync(p));
  let cur = path.resolve(start);
  for (;;) {
    if (stat(path.join(cur, '.git'))) return cur;
    const parent = path.dirname(cur);
    if (parent === cur) return path.resolve(start);
    cur = parent;
  }
}

function statePathFor(start, exists) {
  return path.join(projectRoot(start, exists), STATE_REL);
}

module.exports = { STATE_REL, projectRoot, statePathFor };
