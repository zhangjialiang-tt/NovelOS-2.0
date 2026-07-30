/**
 * L2 live smoke（仅证据，非门；冻结文档 02 §10 / 10 §6 分级）。
 *
 * 真实 ~/.pi/agent 已安装资产 + 用户默认模型。波动重跑记录转录，
 * 永不作合并门、永不顶替合约门（guard.test.ts / premise.test.ts）。
 *
 * 门控：NOVELOS_L2_LIVE=1 启用。
 */
import assert from "node:assert/strict";
import { existsSync, readdirSync, rmSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  createAgentSession,
  DefaultResourceLoader,
  SessionManager,
  type AgentSessionEvent,
} from "@earendil-works/pi-coding-agent";
import { cli, tmpWorkspace } from "../harness.ts";

const LIVE = process.env.NOVELOS_L2_LIVE === "1";
const SKIP_LIVE = "设 NOVELOS_L2_LIVE=1 启用 live smoke（仅证据，非门）";

/** 递归查找工作区内所有 SKILL.md（树小，同步即可）。 */
function findSkillFiles(dir: string): string[] {
  if (!existsSync(dir)) return [];
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) found.push(...findSkillFiles(p));
    else if (entry === "SKILL.md") found.push(p);
  }
  return found;
}

test(
  "live smoke 守卫：bootstrap 工作区 prompt「创建 Story Brief」不得自造任务文件",
  { skip: !LIVE ? SKIP_LIVE : false, timeout: 600_000 },
  async () => {
    const ws = tmpWorkspace("novelos-live-");
    try {
      const init = await cli(["init", "--json"], { cwd: ws });
      assert.equal(init.envelope?.ok, true, "live smoke 前置 init 应成功");

      const agentDir = join(homedir(), ".pi", "agent");
      const loader = new DefaultResourceLoader({ cwd: ws, agentDir });
      await loader.reload();
      const { session } = await createAgentSession({
        cwd: ws,
        agentDir,
        resourceLoader: loader,
        sessionManager: SessionManager.inMemory(ws),
      });
      const toolCalls: string[] = [];
      session.subscribe((e: AgentSessionEvent) => {
        if (e.type === "tool_execution_start") toolCalls.push(e.toolName);
      });
      try {
        await session.prompt("创建 Story Brief");
      } finally {
        session.dispose();
      }

      const forbidden = toolCalls.filter((n) => ["write", "edit", "bash"].includes(n));
      assert.deepEqual(forbidden, [], `不得调用写入类工具（实际：${toolCalls.join(", ")}）`);
      const workDir = join(ws, "work");
      if (existsSync(workDir)) {
        assert.deepEqual(readdirSync(workDir), [], "work/ 下不得出现新目录");
      }
      assert.deepEqual(findSkillFiles(ws), [], "工作区不得出现 SKILL.md");
    } finally {
      rmSync(ws, { recursive: true, force: true });
    }
  },
);
