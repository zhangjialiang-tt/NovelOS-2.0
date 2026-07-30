/**
 * 工具定义合约单测（03 §4 G0 L1 负向可测；04 §2 参数表）。
 *
 * 核心守卫：novelos_decide 的模型参数只有 task_id——决定值（decision/nonce/
 * author_note/revision）绝不进入 schema，模型无从自传决定；buildArgs 白名单
 * 确保即便模型注入多余字段也不落 argv。
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { NOVELOS_TOOL_DEFS, buildArgs } from "../tools.ts";

const NAMES = [
  "novelos_init",
  "novelos_status",
  "novelos_next",
  "novelos_open_task",
  "novelos_submit_candidate",
  "novelos_validate",
  "novelos_present",
  "novelos_decide",
  "novelos_checkpoint",
];

test("nine tools registered with complete metadata", () => {
  assert.deepEqual(
    NOVELOS_TOOL_DEFS.map((d) => d.name).sort(),
    [...NAMES].sort(),
  );
  for (const def of NOVELOS_TOOL_DEFS) {
    assert.ok(def.label.length > 0, `${def.name} label`);
    assert.ok(def.description.length > 0, `${def.name} description`);
    assert.ok(def.promptSnippet.length > 0, `${def.name} promptSnippet`);
    assert.ok(def.parameters !== undefined, `${def.name} parameters`);
  }
});

test("novelos_decide schema leaks no decision channel (03 G0 L1 负向)", () => {
  const decide = NOVELOS_TOOL_DEFS.find((d) => d.name === "novelos_decide");
  assert.ok(decide, "novelos_decide 存在");
  const serialized = JSON.stringify(decide.parameters);
  for (const banned of ["decision", "nonce", "author_note", "revision"]) {
    assert.ok(
      !serialized.includes(`"${banned}"`),
      `decide schema 不得含属性名 ${banned}：${serialized}`,
    );
  }
  assert.ok(serialized.includes('"task_id"'), "decide schema 仅 task_id");
});

test("novelos_open_task schema carries task_type and target_artifact_ref (04 §2 冻结参数)", () => {
  const open = NOVELOS_TOOL_DEFS.find((d) => d.name === "novelos_open_task");
  assert.ok(open, "novelos_open_task 存在");
  const serialized = JSON.stringify(open.parameters);
  assert.ok(serialized.includes('"task_type"'));
  assert.ok(serialized.includes('"target_artifact_ref"'));
});

test("novelos_present / novelos_checkpoint carry optional revision / label (04 §2)", () => {
  const present = NOVELOS_TOOL_DEFS.find((d) => d.name === "novelos_present");
  assert.ok(present, "novelos_present 存在");
  assert.ok(JSON.stringify(present.parameters).includes('"revision"'));
  const checkpoint = NOVELOS_TOOL_DEFS.find((d) => d.name === "novelos_checkpoint");
  assert.ok(checkpoint, "novelos_checkpoint 存在");
  assert.ok(JSON.stringify(checkpoint.parameters).includes('"label"'));
});

test("buildArgs whitelist: injected model fields never reach argv", () => {
  const argv = buildArgs("novelos_decide", { task_id: "t", decision: "accept", nonce: "n" });
  assert.ok(!argv.includes("--decision"), `argv 不得含 --decision：${argv}`);
  assert.ok(!argv.includes("--nonce"), `argv 不得含 --nonce：${argv}`);
  assert.ok(!argv.includes("accept"));
  assert.deepEqual(argv, ["decide", "t", "--json"]);
});

test("buildArgs: per-tool argv shapes and request-id propagation", () => {
  assert.deepEqual(buildArgs("novelos_status", {}), ["status", "--json"]);
  assert.deepEqual(buildArgs("novelos_init", { project_name: "demo" }, "rid-1"), [
    "init",
    "--json",
    "--request-id",
    "rid-1",
    "--project-name",
    "demo",
  ]);
  assert.deepEqual(
    buildArgs("novelos_open_task", { task_type: "premise", brief: "想法" }, "rid-2"),
    ["task", "open", "--json", "--request-id", "rid-2", "--task-type", "premise", "--brief", "想法"],
  );
  assert.deepEqual(buildArgs("novelos_validate", { task_id: "task-001", revision: 2 }), [
    "validate",
    "task-001",
    "--json",
    "--revision",
    "2",
  ]);
  assert.deepEqual(buildArgs("novelos_present", { task_id: "task-001" }, "rid-3"), [
    "present",
    "task-001",
    "--json",
    "--request-id",
    "rid-3",
  ]);
  assert.deepEqual(buildArgs("novelos_submit_candidate", { task_id: "task-001" }, "rid-4"), [
    "candidate",
    "submit",
    "task-001",
    "--json",
    "--request-id",
    "rid-4",
  ]);
  assert.deepEqual(buildArgs("novelos_checkpoint", {}, "rid-5"), [
    "checkpoint",
    "--json",
    "--request-id",
    "rid-5",
  ]);
});

test("buildArgs forwards present --revision and checkpoint --label (04 §2)", () => {
  assert.deepEqual(buildArgs("novelos_present", { task_id: "task-001", revision: 2 }, "rid-p"), [
    "present",
    "task-001",
    "--json",
    "--request-id",
    "rid-p",
    "--revision",
    "2",
  ]);
  assert.deepEqual(buildArgs("novelos_checkpoint", { label: "里程碑" }, "rid-c"), [
    "checkpoint",
    "--json",
    "--request-id",
    "rid-c",
    "--label",
    "里程碑",
  ]);
  // 缺省可选参数不落 argv
  assert.deepEqual(buildArgs("novelos_present", { task_id: "task-001" }, "rid-q"), [
    "present",
    "task-001",
    "--json",
    "--request-id",
    "rid-q",
  ]);
});
