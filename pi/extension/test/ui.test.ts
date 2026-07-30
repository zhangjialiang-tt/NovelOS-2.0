/**
 * ui 渲染单测：状态板四要素（冻结文档 05 §2.2）与 schema 规避（冻结文档 05 §7）。
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  renderNotInitialized,
  renderStatusBoard,
  translateEnvError,
  type NextData,
  type StatusData,
} from "../ui.ts";

const status: StatusData = {
  initialized: true,
  project: "星河彼岸",
  stage: "initialized",
  completed: [],
  issues: [],
  legal_actions: [],
};

const next: NextData = {
  suggested_action: null,
  task_type: null,
  subject: null,
  reason: "工作区已初始化；当前版本尚未开放后续创作动作。",
  reason_code: "NO_ACTION_IMPLEMENTED",
  user_message: "作品已初始化。当前版本尚未开放后续创作动作。",
};

test("board renders the four elements", () => {
  const board = renderStatusBoard(status, next);
  assert.match(board, /作品：《星河彼岸》/);
  assert.match(board, /当前阶段：已初始化/);
  assert.ok(!board.includes("运行时基础"));
  assert.match(board, /已完成：（无）/);
  assert.match(board, /当前问题：无阻塞/);
  assert.match(board, /建议动作：作品已初始化。当前版本尚未开放后续创作动作。/);
});

test("suggested action falls back to reason without user_message", () => {
  const board = renderStatusBoard(status, {
    suggested_action: null,
    task_type: null,
    subject: null,
    reason: "仅理由文案",
  });
  assert.match(board, /建议动作：仅理由文案/);
});

test("completed items get ✓ prefix", () => {
  const board = renderStatusBoard({ ...status, completed: ["故事方向", "故事计划"] }, null);
  assert.match(board, /✓ 故事方向/);
  assert.match(board, /✓ 故事计划/);
});

test("issues rendered when present", () => {
  const board = renderStatusBoard({ ...status, issues: ["第 2 章草稿缺失"] }, null);
  assert.match(board, /当前问题：/);
  assert.match(board, /第 2 章草稿缺失/);
});

test("status-only board omits suggested action (05 §2.1)", () => {
  const board = renderStatusBoard(status, null);
  assert.ok(!board.includes("建议动作"));
});

test("unknown stage passes through human-readably", () => {
  const board = renderStatusBoard({ ...status, stage: "future-stage" }, null);
  assert.match(board, /当前阶段：future-stage/);
});

test("not-initialized line is the frozen wording (05 §2.2)", () => {
  assert.equal(renderNotInitialized(), "作品尚未初始化。告诉我一个故事想法，或用 /novelos 引导创建。");
});

test("no schema leakage in board (05 §7)", () => {
  const board = renderStatusBoard(status, next);
  for (const banned of [".novelos", "sha256:", "legal_actions", "event_id", "source_mode", "Goal", "Phase", "运行时基础"]) {
    assert.ok(!board.includes(banned), `board must not contain ${banned}`);
  }
});

test("env error translation (05 §6.1)", () => {
  assert.equal(translateEnvError("CORE_LAUNCHER_NOT_FOUND"), "核心组件未找到。运行安装脚本。");
  assert.equal(translateEnvError("CORE_VERSION_MISMATCH"), "版本不兼容。更新安装。");
});
