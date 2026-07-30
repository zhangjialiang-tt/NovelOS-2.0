/**
 * NovelOS L2 合约测试基建（冻结文档 10 §2 执行器 / 02 §9 test 模式 / 02 §10 L2 验证范围）。
 *
 * 确定性三件套：
 *   1. 隔离 agentDir（tmp 空目录）——不读 ~/.pi/agent 已安装资产（settings/auth/models/sessions/全局 Skill）；
 *   2. 精确注入当前分支资产——skillsOverride 注入分支 Skill、additionalExtensionPaths 注入分支 Extension，
 *      会话创建后立即断言装载来源（extensionsResult.errors 为空 + novelos skill 的 filePath 指向仓库分支）；
 *   3. pi-ai faux 脚本化 provider——无网络、无真实模型。
 *
 * 辅助模块，无 test 注册。测试自仓库根运行（repoRoot() = process.cwd()）。
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createAgentSession,
  DefaultResourceLoader,
  SessionManager,
  SettingsManager,
  type AgentSession,
  type AgentSessionEvent,
  type LoadExtensionsResult,
  type Skill,
} from "@earendil-works/pi-coding-agent";
import { fauxProvider, type FauxProviderHandle, type FauxResponseStep } from "@earendil-works/pi-ai";

/** Core 信封（与 pi/extension/core-client.ts Envelope 同形）。 */
export interface Envelope {
  ok: boolean;
  data: unknown; // 各动词 data 形状异构；消费方按 in/typeof 窄化
  errors: Array<{ code: string; message: string; path?: string; hint?: string }>;
}

export interface CliResult {
  code: number;
  envelope: Envelope | null;
}

/** 工具 result.details 的 NovelOS 适配形状（tools.ts execute 返回值）。 */
export interface ToolDetails {
  ok: boolean;
  data: unknown; // 各动词 data 形状异构；消费方按 in/typeof 窄化
  errors: Array<{ code: string; message: string; path?: string; hint?: string }>;
  exitCode: number;
}

/** 脚本化模型 token 上限：实际用量 ≪ 此值；超出 = 误配真实模型，立即失败（10 §7 授权上限，数值未冻结）。 */
export const TOKEN_CAP = 20_000;

/** 测试自仓库根运行。 */
export function repoRoot(): string {
  return process.cwd();
}

export function venvPython(): string {
  return process.platform === "win32"
    ? join(repoRoot(), ".venv", "Scripts", "python.exe")
    : join(repoRoot(), ".venv", "bin", "python");
}

/** spawn venv python -m novelos；stdout 最后非空行 JSON.parse 为信封。 */
export function cli(
  args: string[],
  opts?: { cwd?: string; env?: Record<string, string> },
): Promise<CliResult> {
  const { promise, resolve, reject } = Promise.withResolvers<CliResult>();
  const child = spawn(venvPython(), ["-m", "novelos", ...args], {
    cwd: opts?.cwd,
    env: {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      ...opts?.env,
    },
  });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (d) => (stdout += String(d)));
  child.stderr.on("data", (d) => (stderr += String(d)));
  child.on("error", reject);
  child.on("close", (code) => {
    const lines = stdout.split(/\r?\n/).filter((l) => l.trim() !== "");
    const last = lines[lines.length - 1];
    let envelope: Envelope | null = null;
    try {
      const parsed: unknown = last !== undefined ? JSON.parse(last) : null;
      envelope = isEnvelope(parsed) ? parsed : null;
    } catch {
      envelope = null;
    }
    resolve({ code: code ?? -1, envelope });
  });
  return promise;
}

/** 创建隔离 tmp 工作区目录（调用方负责断言与清理）。 */
export function tmpWorkspace(prefix = "novelos-l2-ws-"): string {
  return mkdtempSync(join(tmpdir(), prefix));
}

/**
 * 构造精确 Skill 对象指向当前分支 pi/skill/SKILL.md（字段形状核验自安装包
 * dist/core/skills.d.ts 与 dist/core/source-info.d.ts）。frontmatter 逐行解析
 * name/description 单行值；经 skillsOverride 注入，不经 skill 目录发现语义。
 */
export function branchSkill(): Skill {
  const baseDir = join(repoRoot(), "pi", "skill");
  const filePath = join(baseDir, "SKILL.md");
  const lines = readFileSync(filePath, "utf8").split(/\r?\n/);
  assert.equal(lines[0], "---", "SKILL.md 应以 frontmatter 起始");
  let name = "";
  let description = "";
  for (let i = 1; i < lines.length; i++) {
    if (lines[i] === "---") break;
    const m = /^([\w-]+):\s*(.*)$/.exec(lines[i]);
    if (m === null) continue;
    if (m[1] === "name") name = m[2].trim();
    else if (m[1] === "description") description = m[2].trim();
  }
  assert.equal(name, "novelos", "SKILL.md frontmatter name");
  assert.ok(description.length > 0, "SKILL.md frontmatter description 非空");
  return {
    name: "novelos",
    description,
    filePath,
    baseDir,
    sourceInfo: { path: baseDir, source: "custom", scope: "temporary", origin: "top-level" },
    disableModelInvocation: false,
  };
}

export interface ToolCallRecord {
  name: string;
  args: unknown;
}

export interface ToolResultRecord {
  toolName: string;
  result: unknown;
  isError: boolean;
}


function isErrorItem(v: unknown): v is Envelope["errors"][number] {
  return (
    typeof v === "object" &&
    v !== null &&
    "code" in v &&
    typeof v.code === "string" &&
    "message" in v &&
    typeof v.message === "string"
  );
}

function isEnvelope(v: unknown): v is Envelope {
  return (
    typeof v === "object" &&
    v !== null &&
    "ok" in v &&
    typeof v.ok === "boolean" &&
    "errors" in v &&
    Array.isArray(v.errors)
  );
}

/** 从工具 result（AgentToolResult）提取 NovelOS details；形状不符返回 null。 */
export function toolDetails(result: unknown): ToolDetails | null {
  if (typeof result !== "object" || result === null || !("details" in result)) return null;
  const details: unknown = result.details;
  if (typeof details !== "object" || details === null) return null;
  if (!("ok" in details) || !("errors" in details)) return null;
  const errors: unknown = details.errors;
  return {
    ok: details.ok === true,
    data: "data" in details ? details.data : null,
    errors: Array.isArray(errors) ? errors.filter(isErrorItem) : [],
    exitCode: "exitCode" in details && typeof details.exitCode === "number" ? details.exitCode : -1,
  };
}

function isTextBlock(v: unknown): v is { type: "text"; text: string } {
  return (
    typeof v === "object" &&
    v !== null &&
    "type" in v &&
    v.type === "text" &&
    "text" in v &&
    typeof v.text === "string"
  );
}

/** 工具 content 文本拼接（content: [{type:"text", text}]）。 */
export function toolText(result: unknown): string {
  if (typeof result !== "object" || result === null || !("content" in result)) return "";
  const content: unknown = result.content;
  if (!Array.isArray(content)) return "";
  return content.filter(isTextBlock).map((b) => b.text).join("");
}

/**
 * 隔离、精确注入、脚本化模型的 L2 合约会话。
 * 构造（create）即执行装载断言：证明测的是当前分支资产而非已安装版本。
 */
export class L2ContractSession {
  toolCalls: ToolCallRecord[] = [];
  toolResults: ToolResultRecord[] = [];
  assistantTexts: string[] = [];
  tokens = 0;
  aborted = false;

  readonly wsDir: string;
  readonly agentDir: string;
  readonly loader: DefaultResourceLoader;
  readonly session: AgentSession;
  readonly extensionsResult: LoadExtensionsResult;
  private readonly faux: FauxProviderHandle;
  private readonly unsub: () => void;

  private constructor(
    wsDir: string,
    agentDir: string,
    loader: DefaultResourceLoader,
    session: AgentSession,
    extensionsResult: LoadExtensionsResult,
    faux: FauxProviderHandle,
  ) {
    this.wsDir = wsDir;
    this.agentDir = agentDir;
    this.loader = loader;
    this.session = session;
    this.extensionsResult = extensionsResult;
    this.faux = faux;
    this.unsub = this.session.subscribe((event) => this.onEvent(event));
  }

  static async create(wsDir: string): Promise<L2ContractSession> {
    const agentDir = mkdtempSync(join(tmpdir(), "novelos-l2-agent-"));
    const faux = fauxProvider({ provider: "scripted", api: "scripted" });
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false } });
    const loader = new DefaultResourceLoader({
      cwd: wsDir,
      agentDir,
      settingsManager,
      noExtensions: true, // 关自动发现（保留 additional 路径与内联工厂）
      noPromptTemplates: true,
      noThemes: true,
      noContextFiles: true, // 关 AGENTS.md 上溯
      additionalExtensionPaths: [join(repoRoot(), "pi", "extension", "index.ts")],
      skillsOverride: () => ({ skills: [branchSkill()], diagnostics: [] }),
      extensionFactories: [
        (pi) => {
          pi.registerProvider(faux.provider);
        },
      ],
    });
    await loader.reload();
    const { session, extensionsResult } = await createAgentSession({
      cwd: wsDir,
      agentDir,
      resourceLoader: loader,
      sessionManager: SessionManager.inMemory(wsDir),
      settingsManager,
      model: faux.getModel(),
    });
    const self = new L2ContractSession(wsDir, agentDir, loader, session, extensionsResult, faux);
    self.assertLoaded();
    return self;
  }

  /** 装载断言：扩展零错误 + novelos skill 来自分支路径（tmp agentDir 无任何已安装资产）。 */
  assertLoaded(): void {
    assert.deepEqual(this.extensionsResult.errors, [], "分支扩展装载应零错误");
    const skills = this.loader.getSkills().skills;
    const novelos = skills.find((s) => s.name === "novelos");
    assert.equal(
      novelos?.filePath,
      join(repoRoot(), "pi", "skill", "SKILL.md"),
      "novelos skill 必须来自当前分支",
    );
  }

  /** 设置脚本化响应序列（fauxAssistantMessage/fauxToolCall 组合或 factory）。 */
  script(steps: FauxResponseStep[]): void {
    this.faux.setResponses(steps);
  }

  /** 驱动一轮 prompt；token 超限（实时检查已 abort）则抛错。 */
  async run(): Promise<void> {
    await this.session.prompt("继续");
    if (this.aborted) {
      throw new Error(`token 超限（>${TOKEN_CAP}），疑似误配真实模型：\n${this.dump()}`);
    }
  }

  dispose(): void {
    this.unsub();
    this.session.dispose();
    rmSync(this.agentDir, { recursive: true, force: true });
  }

  /** 失败附证：工具调用序列 + 结果摘要 + token 计数。 */
  dump(): string {
    const calls = this.toolCalls.map((c) => `call ${c.name} ${JSON.stringify(c.args)}`).join("\n");
    const results = this.toolResults
      .map((r) => `result ${r.toolName} isError=${r.isError} ${JSON.stringify(r.result)?.slice(0, 400) ?? ""}`)
      .join("\n");
    return [calls, results, `tokens=${this.tokens}`].join("\n");
  }

  private onEvent(e: AgentSessionEvent): void {
    if (e.type === "tool_execution_start") {
      this.toolCalls.push({ name: e.toolName, args: e.args });
    } else if (e.type === "tool_execution_end") {
      this.toolResults.push({ toolName: e.toolName, result: e.result, isError: e.isError });
    } else if (e.type === "message_end" && e.message.role === "assistant") {
      const text = e.message.content
        .filter((b): b is Extract<typeof b, { type: "text" }> => b.type === "text")
        .map((b) => b.text)
        .join("");
      if (text !== "") this.assistantTexts.push(text);
      const usage = e.message.usage;
      this.tokens += (usage?.input ?? 0) + (usage?.output ?? 0);
      if (this.tokens > TOKEN_CAP) {
        this.aborted = true;
        void this.session.abort();
      }
    }
  }
}
