/**
 * ui 渲染单测：状态板四要素（冻结文档 05 §2.2）与 schema 规避（冻结文档 05 §7）。
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  envelopeErrorsText,
  renderDecidePreview,
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

test("premise stages map to author language (Goal 2)", () => {
  const inProgress = renderStatusBoard({ ...status, stage: "premise_in_progress" }, null);
  assert.match(inProgress, /当前阶段：故事核心创作中/);
  const accepted = renderStatusBoard(
    { ...status, stage: "premise_accepted", completed: ["故事核心方向"] },
    null,
  );
  assert.match(accepted, /当前阶段：故事核心已确定/);
  assert.match(accepted, /✓ 故事核心方向/);
});

test("envelopeErrorsText joins message with hint", () => {
  assert.equal(
    envelopeErrorsText([
      { code: "X", message: "失败甲", hint: "修甲" },
      { code: "Y", message: "失败乙" },
    ]),
    "失败甲（修甲）\n失败乙",
  );
});

test("decide preview renders full text + human summary without internals (05 §7)", () => {
  const text = renderDecidePreview(
    [{ artifact_id: "premise", base_artifact_ref: null, preview_kind: "FULL_TEXT", content: "一句话钩子正文" }],
    {
      changed_files: ["story/premise.md"],
      diff_statistics: { added: 42, removed: 0, files: 1 },
      previous_artifact_revisions: [],
    },
  );
  assert.match(text, /一句话钩子正文/);
  assert.match(text, /变更内容：故事核心/);
  assert.match(text, /新增 42 行 \/ 删除 0 行 \/ 1 个文件/);
  for (const banned of ["story/premise.md", "candidate_revision", "sha256:", "preview_kind"]) {
    assert.ok(!text.includes(banned), `preview 摘要不得含 ${banned}`);
  }
  // previous_artifact_revisions 空 → 隐藏
  assert.ok(!text.includes("影响既有正式版本"));
});
