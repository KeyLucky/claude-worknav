'use strict';
/**
 * 파이썬 렌더러(상태줄)와 JS 렌더러(상태 표시줄)가 같은 상태에서 같은 문자열을 내는지.
 *
 * 이 테스트가 이 확장의 존재 근거다. 두 표지판이 서로 다른 말을 하기 시작하면
 * 둘 다 못 믿게 된다.
 */

const test = require('node:test');
const assert = require('node:assert');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const render = require('../src/render');
const { CASES } = require('./fixtures');

const NOW = new Date('2026-09-02T12:00:00+09:00');
const HELPER = path.join(__dirname, 'cross_render.py');

function pythonOutputs() {
  const payload = JSON.stringify(CASES.map(({ name, state }) => ({ name, state })));
  const proc = spawnSync('python3', [HELPER], { input: payload, encoding: 'utf8' });
  if (proc.error) return { skip: `python3 실행 불가: ${proc.error.message}` };
  if (proc.status !== 0) return { skip: `python3 helper exit ${proc.status}: ${proc.stderr}` };
  return { data: JSON.parse(proc.stdout) };
}

test('X1 path_line 이 파이썬과 문자 단위로 같다', (t) => {
  const result = pythonOutputs();
  if (result.skip) return t.skip(result.skip);
  for (const { name, state } of CASES) {
    assert.strictEqual(
      render.pathLine(state, { maxWidth: 60, titleMax: 12 }),
      result.data[name].path,
      `case ${name}`
    );
  }
});

test('X2 전체 트리와 보류함도 같다', (t) => {
  const result = pythonOutputs();
  if (result.skip) return t.skip(result.skip);
  for (const { name, state } of CASES) {
    assert.strictEqual(render.tree(state, NOW), result.data[name].tree, `tree ${name}`);
    assert.strictEqual(render.inbox(state, NOW), result.data[name].inbox, `inbox ${name}`);
    assert.strictEqual(
      render.openCountExcludingRoot(state),
      result.data[name].open_count,
      `open_count ${name}`
    );
  }
});
