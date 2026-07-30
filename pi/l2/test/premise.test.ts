/**
 * L2 premise 合约场景（确定性合并门；冻结文档 02 §10 / 10 §2；计划 D4）。
 *
 * 脚本化模型驱动全链；作者腿经 evaluation fixture（TEST_FIXTURE）——
 * 绝不产生 INTERACTIVE_UI（02 §7.6 来源边界）。失败即缺陷，不 skip。
 *
 * 门控：NOVELOS_L2=1。自仓库根运行：NOVELOS_L2=1 node --test "pi/l2/test/premise.test.ts"
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai";
import {
  cli,
  L2ContractSession,
  repoRoot,
  tmpWorkspace,
  toolDetails,
  toolText,
} from "../harness.ts";

const L2 = process.env.NOVELOS_L2 === "1";
const SKIP_L2 = "设 NOVELOS_L2=1 启用 L2";
const EVAL_ENV = { NOVELOS_RUN_MODE: "evaluation" };

const FIXTURE_VALID = readFileSync(
  join(repoRoot(), "tests", "fixtures", "premise", "valid.md"),
  "utf8",
);
const ACCEPT_FIXTURE = join(repoRoot(), "tests", "fixtures", "decisions", "accept-premise.json");
const REVISE_FIXTURE = join(repoRoot(), "tests", "fixtures", "decisions", "revise-premise.json");
const BRIEF = "记忆当铺：人们典当记忆换钱，主角是学徒";

const stop = fauxAssistantMessage("done", { stopReason: "stop" });
const call = (name: string, args: Record<string, unknown>) =>
  fauxAssistantMessage([fauxToolCall(name, args)], { stopReason: "toolUse" });

function readEvents(ws: string): Array<Record<string, unknown>> {
  const raw = readFileSync(join(ws, ".novelos", "events.jsonl"), "utf8");
  return raw
    .split(/\r?\n/)
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Record<string, unknown>);
}

/** 脚本驱动到 present，返回会话（调用方 dispose）。 */
async function driveToPresent(ws: string, brief: string | null): Promise<L2ContractSession> {
  const s = await L2ContractSession.create(ws);
  const openArgs: Record<string, unknown> = { task_type: "premise" };
  if (brief !== null) openArgs["brief"] = brief;
  const steps = [
    call("novelos_status", {}),
    call("novelos_next", {}),
    call("novelos_open_task", openArgs),
    call("write", { path: "work/task-001/premise.md", content: FIXTURE_VALID }),
    call("novelos_submit_candidate", { task_id: "task-001" }),
    call("novelos_validate", { task_id: "task-001" }),
    call("novelos_present", { task_id: "task-001" }),
    stop,
  ];
  s.script(steps);
  await s.run();
  return s;
}

test("P1 全链至落盘（脚本化模型 + fixture 决定）", { skip: !L2 ? SKIP_L2 : false }, async () => {
  const ws = tmpWorkspace();
  try {
    const init = await cli(["init", "--json"], { cwd: ws });
    assert.equal(init.envelope?.ok, true);

    const s = await driveToPresent(ws, BRIEF);
    let presentNonce = "";
    try {
      // 工具调用顺序与参数确定性（task-001）
      assert.deepEqual(
        s.toolCalls.map((c) => c.name),
        [
          "novelos_status",
          "novelos_next",
          "novelos_open_task",
          "write",
          "novelos_submit_candidate",
          "novelos_validate",
          "novelos_present",
        ],
        `工具序列\n${s.dump()}`,
      );
      const open = s.toolCalls.find((c) => c.name === "novelos_open_task");
      assert.deepEqual(open?.args, { task_type: "premise", brief: BRIEF });
      for (const name of ["novelos_submit_candidate", "novelos_validate", "novelos_present"]) {
        const c = s.toolCalls.find((t) => t.name === name);
        assert.deepEqual(c?.args, { task_id: "task-001" }, `${name} 参数`);
      }
      // 写入类工具路径全部在 staging 内
      for (const c of s.toolCalls.filter((t) => ["write", "edit", "bash"].includes(t.name))) {
        const args = c.args as { path?: unknown; file_path?: unknown };
        const p = String(args.path ?? args.file_path ?? "");
        assert.ok(p.startsWith("work/task-001/"), `${c.name} 路径逃逸 staging：${p}`);
      }
      // novelos_decide 未被脚本调用
      assert.ok(
        !s.toolCalls.some((c) => c.name === "novelos_decide"),
        "脚本化模型不得自调 decide",
      );
      // present 发布 nonce
      const present = s.toolResults.find((r) => r.toolName === "novelos_present");
      const details = toolDetails(present?.result);
      assert.ok(details?.ok, `present 应成功\n${s.dump()}`);
      const data = details?.data as { pending_decision?: { nonce?: string } };
      presentNonce = String(data?.pending_decision?.nonce ?? "");
      assert.equal(presentNonce.length, 16, "pending nonce 形状");
    } finally {
      s.dispose();
    }

    // 作者决定前：故事核心不得落盘
    assert.ok(!existsSync(join(ws, "story", "premise.md")), "决定前 story/premise.md 不得存在");

    // 作者腿：evaluation fixture（绝不 INTERACTIVE_UI），免 nonce
    const decide = await cli(
      [
        "decide",
        "task-001",
        "--revision",
        "1",
        "--fixture",
        ACCEPT_FIXTURE,
        "--source",
        "TEST_FIXTURE",
        "--json",
      ],
      { cwd: ws, env: EVAL_ENV },
    );
    assert.equal(decide.code, 0, JSON.stringify(decide.envelope));
    assert.equal((decide.envelope?.data as { task_status?: string })?.task_status, "DONE");

    // 落盘 == rev1 规范化字节
    assert.equal(readFileSync(join(ws, "story", "premise.md"), "utf8"), FIXTURE_VALID);

    // COMMITTED：来源 TEST_FIXTURE，nonce == present 发布值
    const committed = readEvents(ws).find((e) => e["type"] === "COMMITTED");
    assert.ok(committed, "应有 COMMITTED 事件");
    const ref = committed?.["decision_ref"] as { source?: string; nonce?: string };
    assert.equal(ref?.source, "TEST_FIXTURE");
    assert.equal(ref?.nonce, presentNonce, "DecisionRef.nonce == present 发布 nonce");

    const scan = await cli(["integrity-scan", "--json"], { cwd: ws });
    assert.equal(scan.code, 0);
  } finally {
    rmSync(ws, { recursive: true, force: true });
  }
});

test("P2 重启恢复 + REVISE 意见交接", { skip: !L2 ? SKIP_L2 : false }, async () => {
  const ws = tmpWorkspace();
  try {
    const init = await cli(["init", "--json"], { cwd: ws });
    assert.equal(init.envelope?.ok, true);

    // 第一段：走到 present → REVISE
    const s1 = await driveToPresent(ws, "A");
    s1.dispose();
    const revise = await cli(
      [
        "decide",
        "task-001",
        "--revision",
        "1",
        "--fixture",
        REVISE_FIXTURE,
        "--source",
        "TEST_FIXTURE",
        "--json",
      ],
      { cwd: ws, env: EVAL_ENV },
    );
    assert.equal(revise.code, 0, JSON.stringify(revise.envelope));

    // 模拟退出重进：同 cwd 重建会话
    const s2 = await L2ContractSession.create(ws);
    try {
      s2.script([
        call("novelos_status", {}),
        call("novelos_next", {}),
        call("novelos_open_task", { task_type: "premise" }), // 无 brief：resume
        call("read", { path: ".novelos/tasks/task-001/context/revision-notes/rev-001.md" }),
        call("write", { path: "work/task-001/premise.md", content: FIXTURE_VALID }),
        call("novelos_submit_candidate", { task_id: "task-001" }),
        call("novelos_validate", { task_id: "task-001" }),
        call("novelos_present", { task_id: "task-001" }),
        stop,
      ]);
      await s2.run();

      // next → continue_task 且携带恢复坐标
      const next = s2.toolResults.find((r) => r.toolName === "novelos_next");
      const nextData = toolDetails(next?.result)?.data as {
        suggested_action?: string;
        task_id?: string;
      };
      assert.equal(nextData?.suggested_action, "continue_task", `next\n${s2.dump()}`);
      assert.equal(nextData?.task_id, "task-001");

      // open_task resumed + original_brief + revision_guidance_ref
      const open = s2.toolResults.find((r) => r.toolName === "novelos_open_task");
      const openData = toolDetails(open?.result)?.data as {
        resumed?: boolean;
        original_brief?: string;
        revision_guidance_ref?: string;
      };
      assert.equal(openData?.resumed, true, `resume\n${s2.dump()}`);
      assert.equal(openData?.original_brief, "A");
      assert.equal(
        openData?.revision_guidance_ref,
        ".novelos/tasks/task-001/context/revision-notes/rev-001.md",
      );

      // Agent 重读意见：read 结果含 note 原文
      const read = s2.toolResults.find((r) => r.toolName === "read");
      assert.ok(read, `应有 read 调用\n${s2.dump()}`);
      assert.ok(toolText(read?.result).includes("把失败代价写具体"), "read 应取回作者意见");

      // rev2 validate 通过
      const validate = s2.toolResults.find((r) => r.toolName === "novelos_validate");
      const validateData = toolDetails(validate?.result)?.data as { valid?: boolean };
      assert.equal(validateData?.valid, true, `rev2 validate\n${s2.dump()}`);
    } finally {
      s2.dispose();
    }

    // 第二段作者腿：ACCEPT → 落盘
    const accept = await cli(
      [
        "decide",
        "task-001",
        "--revision",
        "2",
        "--fixture",
        ACCEPT_FIXTURE,
        "--source",
        "TEST_FIXTURE",
        "--json",
      ],
      { cwd: ws, env: EVAL_ENV },
    );
    assert.equal(accept.code, 0, JSON.stringify(accept.envelope));
    assert.equal(readFileSync(join(ws, "story", "premise.md"), "utf8"), FIXTURE_VALID);
    const scan = await cli(["integrity-scan", "--json"], { cwd: ws });
    assert.equal(scan.code, 0);
  } finally {
    rmSync(ws, { recursive: true, force: true });
  }
});

test("P3 带外写入不自动成为 NovelOS 状态", { skip: !L2 ? SKIP_L2 : false }, async () => {
  const ws = tmpWorkspace();
  try {
    const init = await cli(["init", "--json"], { cwd: ws });
    assert.equal(init.envelope?.ok, true);

    const s = await L2ContractSession.create(ws);
    try {
      s.script([
        call("novelos_status", {}),
        call("write", { path: "work/story-brief/SKILL.md", content: "x" }),
        stop,
      ]);
      await s.run();
    } finally {
      s.dispose();
    }

    // 带外文件确实存在（文档化语义：work/ 不受 managed ledger 覆盖，扫描不会发现）
    assert.ok(existsSync(join(ws, "work", "story-brief", "SKILL.md")), "file_exists");
    // 但它不成为 Task / Artifact
    const tasksDir = join(ws, ".novelos", "tasks");
    assert.deepEqual(readdirSync(tasksDir), [], "task_created 应为 false");
    assert.ok(!existsSync(join(ws, ".novelos", "artifacts", "premise")), "artifact_created 应为 false");
    // integrity-scan 仍 PASS（work/ 未受管——不得声称扫描会发现）
    const scan = await cli(["integrity-scan", "--json"], { cwd: ws });
    assert.equal(scan.code, 0, JSON.stringify(scan.envelope));
  } finally {
    rmSync(ws, { recursive: true, force: true });
  }
});

test("P4 Core 边界：staging 违规文件被拒且不成候选", { skip: !L2 ? SKIP_L2 : false }, async () => {
  const ws = tmpWorkspace();
  try {
    const init = await cli(["init", "--json"], { cwd: ws });
    assert.equal(init.envelope?.ok, true);

    const s = await L2ContractSession.create(ws);
    try {
      s.script([
        call("novelos_status", {}),
        call("novelos_open_task", { task_type: "premise", brief: BRIEF }),
        call("write", { path: "work/task-001/premise.md", content: FIXTURE_VALID }),
        call("write", { path: "work/task-001/SKILL.md", content: "x" }), // 违规
        call("novelos_submit_candidate", { task_id: "task-001" }),
        stop,
      ]);
      await s.run();

      const submit = s.toolResults.find((r) => r.toolName === "novelos_submit_candidate");
      const details = toolDetails(submit?.result);
      assert.ok(details !== null && !details.ok, `submit 应失败\n${s.dump()}`);
      assert.equal(details?.errors[0]?.code, "UNEXPECTED_OUTPUT_FILE");
      assert.ok(
        JSON.stringify(details?.errors).includes("SKILL.md"),
        "错误应指明违规文件",
      );
    } finally {
      s.dispose();
    }

    // CandidateRevision 未生成、无 CANDIDATE_SUBMITTED 事件
    assert.ok(
      !existsSync(join(ws, ".novelos", "tasks", "task-001", "candidates")),
      "candidates/ 不得存在",
    );
    const types = readEvents(ws).map((e) => e["type"]);
    assert.ok(!types.includes("CANDIDATE_SUBMITTED"), "不得有 CANDIDATE_SUBMITTED 事件");
  } finally {
    rmSync(ws, { recursive: true, force: true });
  }
});
