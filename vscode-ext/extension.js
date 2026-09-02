'use strict';
/**
 * worknav 상태 표시줄 확장.
 *
 * 하는 일은 하나다 — .claude/worknav/state.json 을 읽어서 상태 표시줄에 한 줄을 띄운다.
 * Claude Code 와 직접 연결하지 않는다. 파일만 읽는다. 그래서 CLI 나 확장이
 * 업데이트돼도 깨지지 않는다.
 *
 * 절대 하지 않는 것: 상태 파일 쓰기. 파일이 없거나 깨졌을 때 추측해서 그리기.
 * 틀린 표지판은 없는 표지판보다 나쁘다.
 */

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

const render = require('./src/render');
const locate = require('./src/locate');

let item = null;
let itemAlignment = null; // 설정이 바뀌면 상태바 항목을 다시 만들어야 한다
let subscriptions = null;
let output = null;
let timer = null;
let lastSignature = null; // 파일이 안 바뀜면 다시 그리지 않는다
let currentState = null;
let currentFile = null;
const rootCache = new Map(); // 디렉터리 → git 루트. 1초마다 상향 탐색을 반복할 이유가 없다

function config() {
  return vscode.workspace.getConfiguration('worknav');
}

/** 활성 에디터가 속한 워크스페이스 폴더 우선. 없으면 첫 폴더. */
function anchorDir() {
  const editor = vscode.window.activeTextEditor;
  if (editor && editor.document && editor.document.uri.scheme === 'file') {
    const folder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
    if (folder) return folder.uri.fsPath;
    return path.dirname(editor.document.uri.fsPath);
  }
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) return folders[0].uri.fsPath;
  return null;
}

function resolveStateFile() {
  const override = (config().get('statePath') || '').trim();
  if (override) {
    return path.isAbsolute(override)
      ? override
      : path.join(anchorDir() || process.cwd(), override);
  }
  const dir = anchorDir();
  if (!dir) return null;
  if (!rootCache.has(dir)) rootCache.set(dir, locate.statePathFor(dir));
  return rootCache.get(dir);
}

/** alignment 는 항목 생성 시점에만 정해진다. 바뀌면 새로 만드는 수밖에 없다. */
function ensureItem() {
  const wanted =
    config().get('alignment') === 'right'
      ? vscode.StatusBarAlignment.Right
      : vscode.StatusBarAlignment.Left;
  if (item && itemAlignment === wanted) return;
  if (item) item.dispose();
  item = vscode.window.createStatusBarItem(wanted, 100);
  item.command = 'worknav.showTree';
  item.name = 'worknav';
  itemAlignment = wanted;
  if (subscriptions) subscriptions.push(item);
  lastSignature = null; // 새 항목은 비어 있으니 무조건 다시 그린다
}

function hide() {
  currentState = null;
  if (item) item.hide();
}

function readState(file) {
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    return null;
  }
  return render.parseState(text);
}

function paint(state) {
  const cfg = config();
  const line = render.pathLine(state, {
    maxWidth: cfg.get('maxWidth') || 60,
    titleMax: cfg.get('titleMax') || 12,
  });
  if (!line) {
    hide();
    return;
  }
  currentState = state;
  item.text = render.escapeStatusBar(line);
  item.tooltip = render.tooltip(state);

  const warnFrom = cfg.get('warnBackgroundFromDepth');
  let depth = 0;
  try {
    depth = render.depthOf(state, state.cursor);
  } catch {
    depth = 0;
  }
  if (warnFrom > 0 && depth >= warnFrom) {
    item.backgroundColor = new vscode.ThemeColor(
      depth >= warnFrom + 2 ? 'statusBarItem.errorBackground' : 'statusBarItem.warningBackground'
    );
  } else {
    item.backgroundColor = undefined;
  }
  item.show();
}

/**
 * 파일 서명(경로 + mtime + 크기)이 그대로면 아무것도 하지 않는다.
 * 1초마다 도는 경로라 여기서 파싱을 반복하면 이유 없이 CPU 를 쓴다.
 */
function tick(force) {
  ensureItem();
  if (!config().get('enabled')) {
    hide();
    return;
  }
  const file = resolveStateFile();
  if (!file) {
    lastSignature = null;
    hide();
    return;
  }
  let stat = null;
  try {
    stat = fs.statSync(file);
  } catch {
    stat = null;
  }
  const signature = stat ? `${file}:${stat.mtimeMs}:${stat.size}` : `${file}:none`;
  if (!force && signature === lastSignature) return;
  lastSignature = signature;
  currentFile = file;

  if (!stat) {
    hide();
    return;
  }
  const state = readState(file);
  if (!state) {
    hide();
    return;
  }
  paint(state);
}

function restartTimer() {
  if (timer) clearInterval(timer);
  const interval = Math.max(200, config().get('pollIntervalMs') || 1000);
  timer = setInterval(() => tick(false), interval);
}

function showPanel(title, body) {
  if (!output) output = vscode.window.createOutputChannel('worknav');
  output.clear();
  output.appendLine(title);
  output.appendLine('');
  output.appendLine(body);
  if (currentFile) {
    output.appendLine('');
    output.appendLine(`(${currentFile})`);
  }
  output.show(true);
}

function activate(context) {
  subscriptions = context.subscriptions;
  ensureItem();

  context.subscriptions.push(
    vscode.commands.registerCommand('worknav.showTree', () => {
      tick(true);
      if (!currentState) {
        vscode.window.showInformationMessage(
          'worknav 상태 파일이 없습니다. Claude Code 에서 /wn-root 로 목표를 정하고 시작하세요.'
        );
        return;
      }
      showPanel('worknav — 전체 트리', render.tree(currentState));
    }),
    vscode.commands.registerCommand('worknav.showInbox', () => {
      tick(true);
      if (!currentState) {
        vscode.window.showInformationMessage('worknav 상태 파일이 없습니다.');
        return;
      }
      showPanel('worknav — 보류함', render.inbox(currentState));
    }),
    vscode.commands.registerCommand('worknav.refresh', () => tick(true)),
    vscode.window.onDidChangeActiveTextEditor(() => tick(true)),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      rootCache.clear();
      tick(true);
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration('worknav')) {
        rootCache.clear();
        restartTimer();
        tick(true);
      }
    })
  );

  restartTimer();
  tick(true);
}

function deactivate() {
  if (timer) clearInterval(timer);
  timer = null;
  rootCache.clear();
  lastSignature = null;
  currentState = null;
  if (item) item.dispose();
  item = null;
  itemAlignment = null;
  subscriptions = null;
}

module.exports = { activate, deactivate };
