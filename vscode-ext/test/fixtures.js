'use strict';
/** 크로스 체크와 단위 테스트가 함께 쓰는 상태 생성기. 결정적이어야 한다. */

const BASE = '2026-09-02T10:00:00+09:00';

function stamp(minutesFromBase) {
  const d = new Date(new Date(BASE).getTime() + minutesFromBase * 60000);
  // render.py 의 now_iso 와 같은 모양(초 단위, 오프셋 포함)으로 맞춘다.
  const pad = (n) => String(n).padStart(2, '0');
  const tz = 9 * 60; // 고정 +09:00 — 테스트가 실행 환경 시간대에 흔들리면 안 된다
  const local = new Date(d.getTime() + (tz + d.getTimezoneOffset()) * 60000);
  return (
    `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}` +
    `T${pad(local.getHours())}:${pad(local.getMinutes())}:${pad(local.getSeconds())}+09:00`
  );
}

/**
 * titles 로 한 줄짜리 체인을 만들고, parked 개수만큼 보류 노드를 커서 아래 붙인다.
 */
function chainState(titles, parkedTitles) {
  const nodes = {};
  let parent = null;
  let index = 1;
  const ids = [];
  for (const title of titles) {
    const id = 'n' + String(index).padStart(4, '0');
    nodes[id] = {
      title,
      parent,
      state: 'open',
      resume_note: parent === null ? null : `${title} 직전 메모`,
      origin: null,
      opened_at: stamp(index * 3),
      closed_at: null,
      touched_at: stamp(index * 3),
      session_id: null,
    };
    ids.push(id);
    parent = id;
    index += 1;
  }
  const cursor = ids[ids.length - 1] || null;
  for (const title of parkedTitles || []) {
    const id = 'n' + String(index).padStart(4, '0');
    nodes[id] = {
      title,
      parent: cursor,
      state: 'parked',
      resume_note: null,
      origin: cursor,
      opened_at: stamp(index * 3),
      closed_at: null,
      touched_at: stamp(index * 3),
      session_id: null,
    };
    index += 1;
  }
  return {
    version: 1,
    root: ids[0] || null,
    cursor,
    next_id: index,
    config: {
      depth_warn: 3,
      park_ttl_days: 7,
      stale_open_min: 30,
      statusline_max_width: 60,
      title_max: 12,
    },
    nodes,
  };
}

/** 압축 규칙이 실제로 동작하도록 폭·깊이·문자 종류를 흩어 놓는다. */
const CASES = [
  { name: 'depth0', state: chainState(['논문 실험 파트 재현'], []) },
  {
    name: 'depth2-typical',
    state: chainState(['논문 실험 파트 재현', 'ablation S_t 조건 추가', 'seed 고정'], ['로깅 포맷 통일']),
  },
  {
    name: 'depth4-fold',
    state: chainState(
      ['논문 실험 파트 재현', 'ablation S_t 조건 추가', 'seed 고정', '로깅 포맷 통일', 'requirements 핀'],
      ['A', 'B', 'C']
    ),
  },
  {
    name: 'depth7-deep',
    state: chainState(
      ['루트목표', '두번째', '세번째', '네번째', '다섯번째', '여섯번째', '일곱번째', '여덟번째'],
      ['x1', 'x2']
    ),
  },
  {
    name: 'long-ascii',
    state: chainState(
      ['reproduce-experiments-section', 'add-ablation-condition-st', 'fix-nondeterministic-seed'],
      []
    ),
  },
  {
    name: 'very-long-root',
    state: chainState(['아주아주긴한글루트목표이름이여기에들어간다', '자식'], ['보류1', '보류2']),
  },
  { name: 'mixed-width', state: chainState(['ROOT', '한글Mix123', 'ｆｕｌｌｗｉｄｔｈ', 'tail'], []) },
  { name: 'no-cursor', state: (() => { const s = chainState(['루트'], []); s.cursor = null; return s; })() },
  {
    name: 'many-parked',
    state: chainState(['루트', '현재작업'], Array.from({ length: 23 }, (_, i) => `보류${i}`)),
  },
];

module.exports = { BASE, stamp, chainState, CASES };
