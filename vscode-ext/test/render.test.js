'use strict';
/** 표지판이 지켜야 할 것들. 실패하면 상태 표시줄이 거짓말을 한다는 뜻이다. */

const test = require('node:test');
const assert = require('node:assert');

const render = require('../src/render');
const { chainState, CASES } = require('./fixtures');

test('R1 깨진 입력은 전부 null — 추측해서 그리지 않는다', () => {
  for (const bad of ['', '   ', '{', 'null', '[]', '"x"', '{"nodes": []}', '{"nodes": 3}', '{}']) {
    assert.strictEqual(render.parseState(bad), null, `parseState(${JSON.stringify(bad)})`);
  }
  assert.strictEqual(render.pathLine(null), '');
  assert.strictEqual(render.pathLine(undefined), '');
});

test('R2 커서가 없거나 노드에 없으면 빈 줄', () => {
  const state = chainState(['루트', '자식'], []);
  state.cursor = null;
  assert.strictEqual(render.pathLine(state), '');
  state.cursor = 'n9999';
  assert.strictEqual(render.pathLine(state), '');
});

test('R3 루트와 현재는 어떤 폭에서도 남는다', () => {
  const state = chainState(['출발지목표', '중간하나', '중간둘', '중간셋', '현재작업'], []);
  for (const maxWidth of [12, 16, 20, 28, 40, 60, 200]) {
    const line = render.pathLine(state, { maxWidth });
    assert.ok(line.startsWith('⟩ '), `prefix @${maxWidth}: ${line}`);
    // 루트와 현재는 잘릴 수는 있어도 사라지지는 않는다.
    assert.ok(line.includes('출발') || line.includes('출…'), `root kept @${maxWidth}: ${line}`);
    assert.ok(line.includes('현재') || line.includes('현…'), `cursor kept @${maxWidth}: ${line}`);
    assert.ok(line.includes(' d4 '), `depth @${maxWidth}: ${line}`);
  }
});

test('R4 압축 루프는 극단적인 폭에서도 끝난다', () => {
  const titles = Array.from({ length: 40 }, (_, i) => `노드${i}번째작업제목`);
  const state = chainState(titles, []);
  for (const maxWidth of [12, 13, 14, 15, 20]) {
    const started = Date.now();
    const line = render.pathLine(state, { maxWidth });
    assert.ok(Date.now() - started < 1000, `slow @${maxWidth}`);
    assert.ok(line.length > 0);
  }
});

test('R5 깊이와 보류함 개수가 접미사에 정확히 나온다', () => {
  const state = chainState(['a', 'b', 'c'], ['p1', 'p2', 'p3']);
  const line = render.pathLine(state, { maxWidth: 200 });
  assert.ok(line.endsWith('  d2  ⑂3'), line);
  assert.strictEqual(render.depthOf(state, state.cursor), 2);
});

test('R6 parent 순환은 예외를 흘리지 않고 빈 줄로 끝난다', () => {
  const state = chainState(['a', 'b'], []);
  state.nodes.n0001.parent = 'n0002';
  assert.strictEqual(render.pathLine(state), '');
  assert.strictEqual(render.tooltip(state), '');
});

test('R7 열린 노드 수에서 루트는 빠진다', () => {
  const state = chainState(['루트', '자식'], []);
  assert.strictEqual(render.openCountExcludingRoot(state), 1);
  const onlyRoot = chainState(['루트'], []);
  assert.strictEqual(render.openCountExcludingRoot(onlyRoot), 0);
});

test('R8 tooltip 은 복귀지점을 그대로 돌려준다', () => {
  const state = chainState(['논문 재현', 'ablation', 'seed 고정'], []);
  state.nodes.n0002.resume_note = 'runner.py 88줄까지, 다음은 S_t 루프';
  const tip = render.tooltip(state);
  assert.ok(tip.includes('runner.py 88줄까지, 다음은 S_t 루프'), tip);
  assert.ok(tip.includes('← 현재'), tip);
});

test('R9 CJK 는 두 칸으로 세고, 폭 예산을 넘지 않는다', () => {
  assert.strictEqual(render.displayWidth('한글'), 4);
  assert.strictEqual(render.displayWidth('ab'), 2);
  for (const { name, state } of CASES) {
    const line = render.pathLine(state, { maxWidth: 60 });
    if (!line) continue;
    assert.ok(render.displayWidth(line) <= 60, `${name} overflow: ${render.displayWidth(line)}`);
  }
});

test('R10 상태 표시줄 아이콘 문법을 무력화한다', () => {
  const state = chainState(['$(cat foo) 결과 확인', 'x$(rocket)y'], []);
  const line = render.pathLine(state, { maxWidth: 200 });
  // path_line 자체는 파이썬과 같은 문자열을 유지한다.
  assert.ok(line.includes('$(cat'), line);
  // 상태 표시줄로 나갈 때만 아이콘으로 해석되지 않게 끕는다.
  const safe = render.escapeStatusBar(line);
  assert.ok(!/\$\(/.test(safe), safe);
  assert.ok(safe.includes('cat foo'), safe);
  assert.strictEqual(render.escapeStatusBar('평범한 제목'), '평범한 제목');
});

test('R11 폭이 아무리 좁아도 루트와 현재를 버리지는 않는다 — 그래서 하한이 있다', () => {
  const state = chainState(['출발지', '중간', '현재작업'], []);
  const narrow = render.pathLine(state, { maxWidth: 12 });
  // 예산을 못 지키더라도 두 끕은 남는다. 이게 의도된 트레이드오프다.
  assert.ok(narrow.includes('출발') || narrow.includes('출…'), narrow);
  assert.ok(narrow.includes('현재') || narrow.includes('현…'), narrow);
  // 하한이 무한정 크지는 않아야 한다 — 30칸 언저리로 수렴한다.
  assert.ok(render.displayWidth(narrow) <= 34, `하한이 너무 큼: ${render.displayWidth(narrow)}`);
});

test('R12 루트가 없으면 트리는 그리지 않는다', () => {
  assert.strictEqual(render.tree({ nodes: {}, root: null }), '(루트 없음)');
  assert.strictEqual(render.inbox(null), '(상태 없음)');
});
