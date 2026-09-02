'use strict';
/** 다른 프로젝트의 표지판을 띄우면 안 된다. 경계 규칙은 store.py 와 같아야 한다. */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const locate = require('../src/locate');

function tempTree() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'worknav-locate-'));
  const repo = path.join(base, 'repo');
  const deep = path.join(repo, 'a', 'b', 'c');
  fs.mkdirSync(deep, { recursive: true });
  fs.mkdirSync(path.join(repo, '.git'));
  return { base, repo, deep };
}

test('L1 하위 디렉터리에서도 git 루트로 올라간다', () => {
  const { base, repo, deep } = tempTree();
  try {
    assert.strictEqual(locate.projectRoot(deep), fs.realpathSync(repo));
    assert.strictEqual(
      locate.statePathFor(deep),
      path.join(fs.realpathSync(repo), '.claude', 'worknav', 'state.json')
    );
  } finally {
    fs.rmSync(base, { recursive: true, force: true });
  }
});

test('L2 git 이 없으면 시작 지점 자신 — 위로 무한정 올라가지 않는다', () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'worknav-nogit-'));
  const deep = path.join(base, 'x', 'y');
  fs.mkdirSync(deep, { recursive: true });
  try {
    // 루트까지 올라가도 .git 이 없다고 응답하는 환경을 강제한다.
    assert.strictEqual(locate.projectRoot(deep, () => false), path.resolve(deep));
  } finally {
    fs.rmSync(base, { recursive: true, force: true });
  }
});

test('L3 파일로 존재하는 .git(worktree) 도 루트로 인정한다', () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'worknav-wt-'));
  const repo = path.join(base, 'wt');
  const deep = path.join(repo, 'sub');
  fs.mkdirSync(deep, { recursive: true });
  fs.writeFileSync(path.join(repo, '.git'), 'gitdir: /elsewhere\n');
  try {
    assert.strictEqual(locate.projectRoot(deep), fs.realpathSync(repo));
  } finally {
    fs.rmSync(base, { recursive: true, force: true });
  }
});
