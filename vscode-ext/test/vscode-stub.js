'use strict';
/**
 * extension.js 를 vscode 없이 돌리기 위한 최소 스텁.
 *
 * 실제 확장 호스트를 띄우지 않고도 "파일이 이렇게 생겼을 때 상태 표시줄에 무엇이
 * 뜨는가"를 그대로 확인할 수 있다. 스텁은 기록만 하고 판단하지 않는다.
 */

const Module = require('node:module');

function createStub(options) {
  const opts = options || {};
  const settings = Object.assign(
    {
      enabled: true,
      statePath: '',
      maxWidth: 60,
      titleMax: 12,
      alignment: 'left',
      pollIntervalMs: 100000, // 테스트는 타이머 대신 tick 을 직접 부른다
      warnBackgroundFromDepth: 3,
    },
    opts.settings || {}
  );

  // 확장이 alignment 변경 시 항목을 다시 만드는지 보려면 매번 새 객체를 줘야 한다.
  const items = [];
  const makeItem = (alignment) => {
    const created = {
      alignment,
      text: '',
      tooltip: '',
      name: '',
      command: '',
      backgroundColor: undefined,
      visible: false,
      disposed: false,
      show() {
        this.visible = true;
      },
      hide() {
        this.visible = false;
      },
      dispose() {
        this.disposed = true;
        this.visible = false;
      },
    };
    items.push(created);
    return created;
  };

  const commands = new Map();
  const messages = [];
  const outputLines = [];

  const noopEvent = () => ({ dispose() {} });

  const vscode = {
    StatusBarAlignment: { Left: 1, Right: 2 },
    ThemeColor: class ThemeColor {
      constructor(id) {
        this.id = id;
      }
    },
    window: {
      activeTextEditor: undefined,
      createStatusBarItem: (alignment) => makeItem(alignment),
      createOutputChannel: () => ({
        clear() {
          outputLines.length = 0;
        },
        appendLine(line) {
          outputLines.push(line);
        },
        show() {},
        dispose() {},
      }),
      showInformationMessage: (msg) => {
        messages.push(msg);
      },
      onDidChangeActiveTextEditor: noopEvent,
    },
    workspace: {
      workspaceFolders: opts.workspaceDir
        ? [{ uri: { fsPath: opts.workspaceDir, scheme: 'file' } }]
        : undefined,
      getWorkspaceFolder: () => undefined,
      getConfiguration: () => ({
        get: (key) => settings[key],
      }),
      onDidChangeWorkspaceFolders: noopEvent,
      onDidChangeConfiguration: noopEvent,
    },
    commands: {
      registerCommand: (id, fn) => {
        commands.set(id, fn);
        return { dispose() {} };
      },
    },
  };

  const stub = { vscode, items, commands, messages, outputLines, settings };
  // stub.item 은 언제나 "지금 화면에 있는" 항목을 가리킨다.
  Object.defineProperty(stub, 'item', {
    get: () => items[items.length - 1],
  });
  return stub;
}

/** require('vscode') 를 스텁으로 바꾼 채 extension.js 를 새로 로드한다. */
function loadExtension(stub, extensionPath) {
  const original = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return stub.vscode;
    return original.apply(this, arguments);
  };
  try {
    delete require.cache[require.resolve(extensionPath)];
    return require(extensionPath);
  } finally {
    Module._load = original;
  }
}

module.exports = { createStub, loadExtension };
