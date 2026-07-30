/**
 * L2 守卫合约场景（确定性合并门；冻结文档 02 §10 / 10 §2 / 03 G0 L2）。
 *
 * 确定性来源：隔离 agentDir + 分支资产精确注入 + faux 脚本化模型（见 ../harness.ts）。
 * 失败即缺陷：合约场景不允许 skip + issue + 合入（G2「待 D1」跳过是唯一例外，D1 合入即消除）。
 *
 * 门控：NOVELOS_L2=1 启用；默认跳过，每提交节奏（L0+L1+L3）不受影响。
 * 自仓库根运行：NOVELOS_L2=1 node --test "pi/l2/test/guard.test.ts"
 */
import assert from "node:assert/strict";
import { readFileSync, rmSync } from "node:fs";
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

/** D1 着陆探测：core-client 发现链已注入 NOVELOS_HOME 旋钮则 G2 可运行。 */
const D1_LANDED = readFileSync(
  join(repoRoot(), "pi", "extension", "core-client.ts"),
  "utf8",
).includes("NOVELOS_HOME");

const statusThenStop = [
  fauxAssistantMessage([fauxToolCall("novelos_status", {})], { stopReason: "toolUse" }),
  fauxAssistantMessage("done", { stopReason: "stop" }),
];

test("G1 分支扩展装载 + status 管线", { skip: !L2 ? SKIP_L2 : false }, async () => {
  const ws = tmpWorkspace();
  try {
    const init = await cli(["init", "--json"], { cwd: ws });
    assert.equal(init.code, 0, `init 退出码\n${JSON.stringify(init.envelope)}`);
    assert.equal(init.envelope?.ok, true);

    // create() 内含装载断言：extensionsResult.errors 空 + skill filePath 指向分支 SKILL.md。
    // tmp agentDir 无任何已安装资产 → 扩展只能来自分支。
    const s = await L2ContractSession.create(ws);
    try {
      s.script(statusThenStop);
      await s.run();

      const status = s.toolResults.find((r) => r.toolName === "novelos_status");
      assert.ok(status, `应有 novelos_status 工具结果\n${s.dump()}`);
      const details = toolDetails(status.result);
      assert.ok(details, `details 形状\n${s.dump()}`);
      const data = details.data;
      assert.ok(
        data !== null && typeof data === "object" && "initialized" in data,
        `status data 应含 initialized\n${s.dump()}`,
      );
      assert.equal(data.initialized, true);
      assert.ok(
        toolText(status.result).includes("project"),
        `content 文本应为可解析状态板 JSON\n${s.dump()}`,
      );
    } finally {
      s.dispose();
    }
  } finally {
    rmSync(ws, { recursive: true, force: true });
  }
});

test(
  "G2 Core 缺失转译",
  {
    skip: !L2
      ? SKIP_L2
      : !D1_LANDED
        ? "待 D1：NOVELOS_HOME/NOVELOS_CORE_STRICT 旋钮未实装（D1 合入后必须运行）"
        : false,
  },
  async () => {
    const saved = {
      core: process.env.NOVELOS_CORE,
      home: process.env.NOVELOS_HOME,
      strict: process.env.NOVELOS_CORE_STRICT,
    };
    const fakeHome = tmpWorkspace("novelos-l2-home-"); // 空家目录：无 .novelos/launcher.json
    const ws = tmpWorkspace();
    process.env.NOVELOS_CORE = "nonexistent-cmd-xyz";
    process.env.NOVELOS_HOME = fakeHome;
    process.env.NOVELOS_CORE_STRICT = "1";
    try {
      const s = await L2ContractSession.create(ws);
      try {
        s.script(statusThenStop);
        await s.run();

        const status = s.toolResults.find((r) => r.toolName === "novelos_status");
        assert.ok(status, `应有 novelos_status 工具结果\n${s.dump()}`);
        const details = toolDetails(status.result);
        assert.ok(details, `details 形状\n${s.dump()}`);
        assert.equal(details.ok, false, "握手应失败");
        assert.equal(details.errors[0]?.code, "CORE_LAUNCHER_NOT_FOUND");
        // D1 后逐字转译（05 §6.1，ui.ts translateEnvError）
        assert.equal(toolText(status.result), "核心组件未找到。运行安装脚本。");
      } finally {
        s.dispose();
      }
    } finally {
      for (const [key, value] of [
        ["NOVELOS_CORE", saved.core],
        ["NOVELOS_HOME", saved.home],
        ["NOVELOS_CORE_STRICT", saved.strict],
      ] as const) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
      rmSync(ws, { recursive: true, force: true });
      rmSync(fakeHome, { recursive: true, force: true });
    }
  },
);

test("G3 分支 Skill 装载断言", { skip: !L2 ? SKIP_L2 : false }, async () => {
  const ws = tmpWorkspace();
  try {
    const s = await L2ContractSession.create(ws);
    try {
      s.script([fauxAssistantMessage("done", { stopReason: "stop" })]);
      await s.run();

      const skills = s.loader.getSkills().skills;
      const novelos = skills.filter((sk) => sk.name === "novelos");
      assert.equal(novelos.length, 1, `novelos skill 恰一个\n${JSON.stringify(skills)}`);
      assert.equal(novelos[0]?.filePath, join(repoRoot(), "pi", "skill", "SKILL.md"));
      const desc = novelos[0]?.description ?? "";
      assert.ok(desc.length > 0 && desc.length <= 1024, "description 非空且 ≤1024（05/02 约束）");
      assert.deepEqual(s.extensionsResult.errors, []);
    } finally {
      s.dispose();
    }
  } finally {
    rmSync(ws, { recursive: true, force: true });
  }
});
