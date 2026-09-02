'use strict';
/**
 * worknav 표시 규칙 — src/render.py 의 JS 이식본.
 *
 * 두 렌더러가 같은 state.json 을 읽는다. 어긋나면 표지판이 거짓말을 하므로,
 * 같은 입력에 같은 문자열이 나오는지 test/cross_python.test.js 가 매번 확인한다.
 * 여기에 규칙을 새로 만들지 않는다. 규칙이 바뀌면 render.py 를 먼저 고친다.
 */

const SYMBOL = { done: '✓', open: '●', parked: '⑂', dropped: '✗' };

const DEFAULT_CONFIG = {
  depth_warn: 3,
  park_ttl_days: 7,
  stale_open_min: 30,
  statusline_max_width: 60,
  title_max: 12,
};

const CYCLE_GUARD = 1000;

/** 상태 파일 파싱. 깨졌으면 null — 추측해서 그리지 않는다. */
function parseState(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  if (!data.nodes || typeof data.nodes !== 'object' || Array.isArray(data.nodes)) return null;
  data.config = Object.assign({}, DEFAULT_CONFIG, data.config || {});
  return data;
}

function chars(text) {
  return Array.from(text || '');
}

/** CJK 를 2칸으로 세는 근사. render.py 의 display_width 와 같은 구간을 쓴다. */
function displayWidth(text) {
  let width = 0;
  for (const ch of chars(text)) {
    const code = ch.codePointAt(0);
    const wide =
      (code >= 0x1100 && code <= 0x115f) ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe30 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6);
    width += wide ? 2 : 1;
  }
  return width;
}

function truncate(text, limit) {
  const cleaned = (text || '').trim().replace(/\n/g, ' ');
  const cs = chars(cleaned);
  if (cs.length <= limit) return cleaned;
  if (limit <= 1) return '…';
  return cs.slice(0, limit - 1).join('') + '…';
}

function node(state, id) {
  const found = state.nodes[id];
  if (!found) throw new Error('노드 없음: ' + id);
  return found;
}

function pathIds(state, id) {
  const chain = [id];
  let cur = node(state, id).parent;
  let guard = 0;
  while (cur !== null && cur !== undefined) {
    chain.push(cur);
    cur = node(state, cur).parent;
    if (++guard > CYCLE_GUARD) throw new Error('parent cycle at ' + id);
  }
  chain.reverse();
  return chain;
}

function depthOf(state, id) {
  return pathIds(state, id).length - 1;
}

function sortedByOpened(entries) {
  return entries.sort((a, b) => {
    const ao = a[1].opened_at || '';
    const bo = b[1].opened_at || '';
    if (ao !== bo) return ao < bo ? -1 : 1;
    return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0;
  });
}

function nodesInState(state, wanted) {
  return sortedByOpened(Object.entries(state.nodes).filter(([, nd]) => nd.state === wanted));
}

function parkedNodes(state) {
  return nodesInState(state, 'parked');
}

function openNodes(state) {
  return nodesInState(state, 'open');
}

/** 루트는 목표 자체라 항상 열려 있다. 세면 노이즈가 된다. */
function openCountExcludingRoot(state) {
  return openNodes(state).filter(([id]) => id !== state.root).length;
}

function children(state, id) {
  return sortedByOpened(Object.entries(state.nodes).filter(([, nd]) => nd.parent === id));
}

/**
 * ⟩ 논문재현 › ablation › seed고정  d2  ⑂9
 *
 * 압축 규칙: 루트와 현재는 무슨 일이 있어도 남긴다.
 * 길을 잃는다는 건 정확히 출발지를 잊는다는 뜻이다.
 */
function pathLine(state, options) {
  const opts = options || {};
  if (!state) return '';
  const cursor = state.cursor;
  if (!cursor || !state.nodes[cursor]) return '';

  const config = state.config || DEFAULT_CONFIG;
  const maxWidth = opts.maxWidth || config.statusline_max_width || 60;
  const titleMax = opts.titleMax || config.title_max || 12;

  let chain;
  try {
    chain = pathIds(state, cursor);
  } catch {
    return '';
  }
  const depth = chain.length - 1;
  const parked = parkedNodes(state).length;
  const suffix = `  d${depth}  ⑂${parked}`;
  const budget = maxWidth - displayWidth(suffix);

  const titles = chain.map((id) => state.nodes[id].title);

  // kept 는 남길 인덱스의 오름차순 목록. 끊긴 자리에만 … 를 넣는다.
  const build = (kept, limit) => {
    const parts = [];
    let previous = null;
    for (const index of kept) {
      if (previous !== null && index !== previous + 1) parts.push('…');
      parts.push(truncate(titles[index], limit));
      previous = index;
    }
    return '⟩ ' + parts.join(' › ');
  };

  // 1단계: 가운데 항목을 하나씩 버린다. 목록이 매번 줄어드니 반드시 끝난다.
  // 첫 항목(루트)과 마지막 항목(현재)은 splice 대상에서 구조적으로 빠진다.
  const kept = titles.map((_, i) => i);
  let limit = titleMax;
  while (displayWidth(build(kept, limit)) > budget && kept.length > 2) {
    kept.splice(Math.floor(kept.length / 2), 1);
  }
  // 2단계: 그래도 넘치면 제목 자체를 줄인다. 루트와 현재는 끝까지 남는다.
  while (displayWidth(build(kept, limit)) > budget && limit > 4) {
    limit -= 2;
  }
  return build(kept, limit) + suffix;
}

/**
 * 상태 표시줄 전용 후처리.
 *
 * VS Code 상태 표시줄은 `$(icon-name)` 을 아이콘 문법으로 해석한다. 노드 제목은
 * 사람이 자유롭게 쓰는 문자열이라 "$(cat foo) 결과 확인" 같은 게 들어올 수 있고,
 * 그대로 넘기면 표지판 한가운데가 통 사라진다. 여기서만 막는다 — path_line
 * 자체는 파이썬 상태줄과 같은 문자열을 유지해야 한다.
 */
function escapeStatusBar(text) {
  return (text || '').replace(/\$\(/g, '$​(');
}

function parseIso(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function nodeMeta(nd, now) {
  if (nd.state === 'parked') return '   park';
  const started = parseIso(nd.opened_at);
  if (!started) return '';
  const ended = parseIso(nd.closed_at) || now;
  const minutes = Math.max(0, Math.floor((ended - started) / 60000));
  return `   ${minutes}m`;
}

function isExpired(nd, now, ttlDays) {
  const started = parseIso(nd.opened_at);
  if (!started) return false;
  return Math.floor((now - started) / 86400000) >= ttlDays;
}

/** 전체 트리 — 요청했을 때만. 작업 중에 형제 노드를 보여주면 가지치기를 부추긴다. */
function tree(state, now) {
  if (!state || !state.root) return '(루트 없음)';
  const ref = now || new Date();
  const cursor = state.cursor;
  const lines = [];

  const emit = (id, prefix, isLast, isRoot) => {
    const nd = state.nodes[id];
    if (!nd) return;
    const symbol = SYMBOL[nd.state] || '?';
    let branchPrefix;
    if (isRoot) {
      lines.push(nd.title || '');
      branchPrefix = '';
    } else {
      const connector = isLast ? '└─ ' : '├─ ';
      const here = id === cursor ? '  ← 현재' : '';
      lines.push(`${prefix}${connector}${symbol} ${nd.title || ''}${nodeMeta(nd, ref)}${here}`);
      branchPrefix = prefix + (isLast ? '   ' : '│  ');
    }
    const kids = children(state, id);
    kids.forEach(([kidId], index) => emit(kidId, branchPrefix, index === kids.length - 1, false));
  };

  emit(state.root, '', true, true);

  const ttl = (state.config || {}).park_ttl_days || 7;
  const parked = parkedNodes(state);
  const expired = parked.filter(([, nd]) => isExpired(nd, ref, ttl)).length;
  lines.push('');
  lines.push(
    `열린 노드 ${openCountExcludingRoot(state)} · 보류함 ${parked.length} (${expired}개 ${ttl}일 경과)`
  );
  return lines.join('\n');
}

function inbox(state, now) {
  if (!state) return '(상태 없음)';
  const ref = now || new Date();
  const ttl = (state.config || {}).park_ttl_days || 7;
  const items = parkedNodes(state);
  if (items.length === 0) return '보류함 비어 있음';
  const lines = [`보류함 ${items.length}`];
  for (const [id, nd] of items) {
    const started = parseIso(nd.opened_at);
    const days = started ? Math.floor((ref - started) / 86400000) : 0;
    const mark = days >= ttl ? '  [만료]' : '';
    const origin = nd.origin && state.nodes[nd.origin] ? ` (발생: ${state.nodes[nd.origin].title})` : '';
    lines.push(`  ${id} ⑂ ${nd.title}${origin}  ${days}일${mark}`);
  }
  return lines.join('\n');
}

/** 상태바 마우스오버용. 여기서는 폭 제한이 없으니 자르지 않고 전부 보여준다. */
function tooltip(state) {
  if (!state || !state.cursor || !state.nodes[state.cursor]) return '';
  let chain;
  try {
    chain = pathIds(state, state.cursor);
  } catch {
    return '';
  }
  const lines = [];
  chain.forEach((id, index) => {
    const nd = state.nodes[id];
    const indent = '  '.repeat(index);
    const mark = index === chain.length - 1 ? '  ← 현재' : '';
    lines.push(`${indent}${index === 0 ? 'ROOT ' : '└─ '}${nd.title}${mark}`);
    if (nd.resume_note) lines.push(`${indent}   복귀지점: ${nd.resume_note}`);
  });
  lines.push('');
  lines.push(`보류함 ${parkedNodes(state).length} · 열린 노드 ${openCountExcludingRoot(state)}`);
  return lines.join('\n');
}

module.exports = {
  DEFAULT_CONFIG,
  SYMBOL,
  parseState,
  displayWidth,
  truncate,
  pathIds,
  depthOf,
  parkedNodes,
  openNodes,
  openCountExcludingRoot,
  children,
  pathLine,
  escapeStatusBar,
  tree,
  inbox,
  tooltip,
};
