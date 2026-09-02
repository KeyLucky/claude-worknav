'use strict';
/**
 * 진짜 wn.py 로 만든 상태 파일을 확장이 읽어서 상태 표시줄에 무엇을 띄우는가.
 *
 * 합성 픽스처는 스키마를 내가 상상한 대로 맞춰 놓기 때문에, CLI 가 실제로 쓰는
 * 파일과 어긋나도 통과한다. 그래서 여기서는 CLI 를 그대로 돌린다.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const { createStub, loadExtension } = require('./vscode-stub');

const PROJECT = path.join(__dirname, '..', '..');
const WN = path.join(PROJECT, 'src', 'wn.py');
const EXTENSION = path.join(__dirname, '..', 'extension.js');

function pythonMissing() {
  const probe = spawnSync('python3', ['-c', 'print(1)'], { encoding: 'utf8' });
  return probe.error || probe.status !== 0;
}

function makeRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'worknav-e2e-'));
  fs.mkdirSync(path.join(dir, '.git'));
  return dir;
}

function wn(repo, args) {
  const proc = spawnSync('python3', [WN, '--root', repo, ...args], { encoding: 'utf8' });
  return { code: proc.status, out: (proc.stdout || '').trim(), err: (proc.stderr || '').trim() };
}

function bootExtension(repo, settings) {
  const stub = createStub({ workspaceDir: repo, settings });
  const ext = loadExtension(stub, EXTENSION);
  ext.activate({ subscriptions: [] });
  return { stub, ext };
}

test('E1 CLI 가 만든 상태를 그대로 표지판으로 띄운다', (t) => {
  if (pythonMissing()) return t.skip('python3 없음');
  const repo = makeRepo();
  try {
    assert.strictEqual(wn(repo, ['root', '논문 실험 파트 재현']).code, 0);
    assert.strictEqual(
      wn(repo, ['push', 'ablation S_t 조건 추가', '--resume-note', '데이터 로더까지 확인함']).code,
      0
    );
    assert.strictEqual(wn(repo, ['push', 'seed 고정', '--resume-note', 'runner.py 88줄까지']).code, 0);
    assert.strictEqual(wn(repo, ['park', '로깅 포맷 통일']).code, 0);

    const { stub, ext } = bootExtension(repo);
    try {
      assert.ok(stub.item.visible, '표지판이 떠 있어야 한다');
      // 파이썬 상태줄과 같은 문자열이어야 한다 — 두 표지판이 다른 말을 하면 안 된다.
      assert.strictEqual(stub.item.text, wn(repo, ['path', '--no-color']).out);
      assert.ok(stub.item.text.includes('논문 실험 파트'), stub.item.text);
      assert.ok(stub.item.text.endsWith('  d2  ⑂1'), stub.item.text);
      // 45분 뒤에 쓸 문장이 마우스오버에 들어 있어야 한다.
      assert.ok(stub.item.tooltip.includes('runner.py 88줄까지'), stub.item.tooltip);
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('E2 상태가 바뀌면 다음 확인에서 따라간다', (t) => {
  if (pythonMissing()) return t.skip('python3 없음');
  const repo = makeRepo();
  try {
    wn(repo, ['root', '루트 목표']);
    wn(repo, ['push', '자식 작업', '--resume-note', '메모']);
    const { stub, ext } = bootExtension(repo);
    try {
      const before = stub.item.text;
      assert.ok(before.endsWith('  d1  ⑂0'), before);

      wn(repo, ['pop']);
      stub.commands.get('worknav.refresh')();
      assert.notStrictEqual(stub.item.text, before);
      assert.ok(stub.item.text.endsWith('  d0  ⑂0'), stub.item.text);
      assert.strictEqual(stub.item.text, wn(repo, ['path', '--no-color']).out);
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('E3 파일이 없거나 깨지면 아무것도 띄우지 않는다', (t) => {
  if (pythonMissing()) return t.skip('python3 없음');
  const repo = makeRepo();
  try {
    wn(repo, ['root', '루트 목표']);
    const statePath = path.join(repo, '.claude', 'worknav', 'state.json');
    const { stub, ext } = bootExtension(repo);
    try {
      assert.ok(stub.item.visible);

      for (const broken of ['', '   ', '{', '[]', '{"nodes": []}']) {
        fs.writeFileSync(statePath, broken);
        stub.commands.get('worknav.refresh')();
        assert.strictEqual(stub.item.visible, false, `깨진 입력에 표지판이 남았다: ${broken}`);
      }

      fs.rmSync(statePath);
      stub.commands.get('worknav.refresh')();
      assert.strictEqual(stub.item.visible, false);

      // 정상 상태가 돌아오면 다시 떠야 한다.
      wn(repo, ['root', '되살린 목표', '--force']);
      stub.commands.get('worknav.refresh')();
      assert.ok(stub.item.visible);
      assert.ok(stub.item.text.includes('되살린'), stub.item.text);
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('E4 깊이가 깊어지면 배경색으로 먼저 알린다', (t) => {
  if (pythonMissing()) return t.skip('python3 없음');
  const repo = makeRepo();
  try {
    wn(repo, ['root', '루트']);
    const { stub, ext } = bootExtension(repo);
    try {
      assert.strictEqual(stub.item.backgroundColor, undefined, 'd0 에서는 배경색 없음');

      wn(repo, ['push', '자식1', '--resume-note', 'm']);
      wn(repo, ['push', '자식2', '--resume-note', 'm']);
      stub.commands.get('worknav.refresh')();
      assert.strictEqual(stub.item.backgroundColor, undefined, 'd2 는 아직 경고 아님');

      // 깊이 3부터는 게이트가 막으므로 --force 로 통과시킨다.
      wn(repo, ['push', '자식3', '--resume-note', 'm', '--force']);
      stub.commands.get('worknav.refresh')();
      assert.ok(stub.item.backgroundColor, 'd3 에서는 경고 배경');
      assert.strictEqual(stub.item.backgroundColor.id, 'statusBarItem.warningBackground');

      wn(repo, ['push', '자식4', '--resume-note', 'm', '--force']);
      wn(repo, ['push', '자식5', '--resume-note', 'm', '--force']);
      stub.commands.get('worknav.refresh')();
      assert.strictEqual(stub.item.backgroundColor.id, 'statusBarItem.errorBackground');
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('E5 트리 명령은 파이썬 wn tree 와 같은 그림을 보여준다', (t) => {
  if (pythonMissing()) return t.skip('python3 없음');
  const repo = makeRepo();
  try {
    wn(repo, ['root', '논문 실험 파트 재현']);
    wn(repo, ['push', 'ablation 수정', '--resume-note', 'm']);
    wn(repo, ['park', '로깅 포맷 통일']);
    wn(repo, ['pop']);
    const { stub, ext } = bootExtension(repo);
    try {
      stub.commands.get('worknav.showTree')();
      const shown = stub.outputLines.join('\n');
      const expected = wn(repo, ['tree']).out;
      for (const line of expected.split('\n')) {
        if (line.trim()) assert.ok(shown.includes(line), `트리 줄 누락: ${line}\n---\n${shown}`);
      }
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('E6 상태 파일이 아예 없는 폴더에서도 조용히 넘어간다', (t) => {
  const repo = makeRepo();
  try {
    const { stub, ext } = bootExtension(repo);
    try {
      assert.strictEqual(stub.item.visible, false);
      stub.commands.get('worknav.showTree')();
      assert.strictEqual(stub.messages.length, 1, '안내 메시지 한 번');
      assert.ok(stub.messages[0].includes('/wn-root'), stub.messages[0]);
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('E8 alignment 를 바꾸면 상태바 항목을 다시 만든다', (t) => {
  if (pythonMissing()) return t.skip('python3 없음');
  const repo = makeRepo();
  try {
    wn(repo, ['root', '루트 목표']);
    const { stub, ext } = bootExtension(repo, { alignment: 'left' });
    try {
      const first = stub.item;
      assert.strictEqual(first.alignment, 1);
      stub.settings.alignment = 'right';
      stub.commands.get('worknav.refresh')();
      assert.notStrictEqual(stub.item, first, '항목이 새로 만들어져야 한다');
      assert.strictEqual(stub.item.alignment, 2);
      assert.ok(first.disposed, '이전 항목은 정리돼야 한다');
      assert.ok(stub.item.visible && stub.item.text.includes('루트 목표'), stub.item.text);
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('E9 제목에 $( 가 있어도 표지판이 통째로 사라지지 않는다', (t) => {
  if (pythonMissing()) return t.skip('python3 없음');
  const repo = makeRepo();
  try {
    wn(repo, ['root', '$(rocket) 배포 준비']);
    const { stub, ext } = bootExtension(repo);
    try {
      assert.ok(stub.item.visible);
      assert.ok(!/\$\(/.test(stub.item.text), stub.item.text);
      assert.ok(stub.item.text.includes('rocket'), stub.item.text);
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('E7 enabled=false 면 표지판을 내린다', (t) => {
  if (pythonMissing()) return t.skip('python3 없음');
  const repo = makeRepo();
  try {
    wn(repo, ['root', '루트 목표']);
    const { stub, ext } = bootExtension(repo, { enabled: false });
    try {
      assert.strictEqual(stub.item.visible, false);
      stub.settings.enabled = true;
      stub.commands.get('worknav.refresh')();
      assert.ok(stub.item.visible);
    } finally {
      ext.deactivate();
    }
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});
