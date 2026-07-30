/**
 * NovelOS 工具注册（冻结文档 04 §2）。
 *
 * Goal 1 三工具（novelos_init / novelos_status / novelos_next）+
 * Goal 2 六工具（open_task / submit_candidate / validate / present / decide / checkpoint）。
 *
 * 薄适配三件事（冻结文档 02 §6.3）：校验/转换参数 → 调用 Core launcher → 解析 JSON 映射为 tool result。
 * 幂等：init/open_task/submit/present/checkpoint 每次调用生成 per-call UUID 作 --request-id（04 §1.5），
 * 不暴露给模型；validate 领域幂等、decide 一次性，均不带 request-id。
 *
 * novelos_decide：模型参数仅 task_id（03 §4 G0 负向：schema 不含决定值）；决定值经 TUI 中介
 * （04 §3.6 五步、05 §8.3 无 UI 守卫）。buildArgs 白名单：只取 schema 声明参数落 argv。
 */
import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type, type TSchema } from "typebox";
import type { CallResult, CoreClient, Handshake } from "./core-client.ts";
import {
  envelopeErrorsText,
  renderDecidePreview,
  translateEnvError,
  type PreviewContentItem,
  type PresentPacket,
} from "./ui.ts";

type HandshakeGetter = () => Promise<Handshake>;

export interface NovelosToolDef {
  name: string;
  label: string;
  description: string;
  promptSnippet: string;
  parameters: TSchema;
}

/** 九工具纯数据定义（04 §2 参数表；decide 仅 task_id——决定值经 UI，不入 schema）。 */
export const NOVELOS_TOOL_DEFS: NovelosToolDef[] = [
  {
    name: "novelos_init",
    label: "NovelOS 初始化",
    description: "把当前作品目录初始化为 NovelOS Workspace；未初始化时是唯一入口。",
    promptSnippet: "初始化 NovelOS 作品目录",
    parameters: Type.Object({
      project_name: Type.Optional(Type.String({ description: "项目名；缺省取目录名" })),
    }),
  },
  {
    name: "novelos_status",
    label: "NovelOS 状态",
    description: "查询作品状态板数据：阶段、已完成、当前问题、合法动作。只读。",
    promptSnippet: "查询 NovelOS 状态板",
    parameters: Type.Object({}),
  },
  {
    name: "novelos_next",
    label: "NovelOS 下一步",
    description: "推导下一步建议动作与理由。只读，不创建任何对象。",
    promptSnippet: "获取 NovelOS 下一步建议",
    parameters: Type.Object({}),
  },
  {
    name: "novelos_open_task",
    label: "NovelOS 开任务",
    description: "创建或恢复创作任务；返回 task_id/staging_path/instructions_ref。创建时 brief 必填。",
    promptSnippet: "开启或恢复 NovelOS 创作任务",
    parameters: Type.Object({
      task_type: Type.String({ description: "任务类型；当前仅 premise" }),
      subject: Type.Optional(Type.String({ description: "任务主题；缺省由 Core 取值" })),
      brief: Type.Optional(Type.String({ description: "用户故事想法摘要（必需，先对话收集）" })),
      target_artifact_ref: Type.Optional(
        Type.String({ description: "Change Task 主目标；premise 不接受" }),
      ),
    }),
  },
  {
    name: "novelos_submit_candidate",
    label: "NovelOS 提交候选",
    description: "把 staging 区内容提交为冻结候选；返回 candidate_revision 与 content_hash。",
    promptSnippet: "提交 NovelOS 候选",
    parameters: Type.Object({
      task_id: Type.String({ description: "任务 id（取自 novelos_open_task 返回值）" }),
    }),
  },
  {
    name: "novelos_validate",
    label: "NovelOS 校验候选",
    description: "对冻结候选做领域纯检查；失败按 errors 的 hint 修复后重新 submit + validate。",
    promptSnippet: "校验 NovelOS 候选",
    parameters: Type.Object({
      task_id: Type.String({ description: "任务 id" }),
      revision: Type.Optional(Type.Number({ description: "候选版本号；缺省当前候选" })),
    }),
  },
  {
    name: "novelos_present",
    label: "NovelOS 呈现候选",
    description: "校验通过后呈现候选待作者决定；发布决定机会（pending）。",
    promptSnippet: "呈现 NovelOS 候选待决定",
    parameters: Type.Object({
      task_id: Type.String({ description: "任务 id" }),
    }),
  },
  {
    name: "novelos_decide",
    label: "NovelOS 作者决定",
    description:
      "中介作者对候选的决定（ACCEPT/REVISE/REJECT）。决定值只能经交互式对话框取得；模型不传决定值。",
    promptSnippet: "请作者决定 NovelOS 候选",
    parameters: Type.Object({
      task_id: Type.String({ description: "任务 id" }),
    }),
  },
  {
    name: "novelos_checkpoint",
    label: "NovelOS 检查点",
    description: "保存进度检查点；清理已完成任务的 staging。",
    promptSnippet: "保存 NovelOS 进度检查点",
    parameters: Type.Object({}),
  },
];

function stringArg(params: Record<string, unknown>, key: string, flag: string): string[] {
  const v = params[key];
  return typeof v === "string" && v.trim() !== "" ? [flag, v] : [];
}

function numberArg(params: Record<string, unknown>, key: string, flag: string): string[] {
  const v = params[key];
  return typeof v === "number" && Number.isFinite(v) ? [flag, String(v)] : [];
}

/** 白名单式 argv 构造：只取 schema 声明参数落 argv，模型注入的多余字段被丢弃。 */
export function buildArgs(
  name: string,
  params: Record<string, unknown>,
  requestId?: string,
): string[] {
  const rid = requestId !== undefined ? ["--request-id", requestId] : [];
  switch (name) {
    case "novelos_init":
      return ["init", "--json", ...rid, ...stringArg(params, "project_name", "--project-name")];
    case "novelos_status":
      return ["status", "--json"];
    case "novelos_next":
      return ["next", "--json"];
    case "novelos_open_task":
      return [
        "task",
        "open",
        "--json",
        ...rid,
        "--task-type",
        String(params["task_type"] ?? ""),
        ...stringArg(params, "subject", "--subject"),
        ...stringArg(params, "brief", "--brief"),
        ...stringArg(params, "target_artifact_ref", "--target-artifact-ref"),
      ];
    case "novelos_submit_candidate":
      return ["candidate", "submit", String(params["task_id"] ?? ""), "--json", ...rid];
    case "novelos_validate":
      return ["validate", String(params["task_id"] ?? ""), "--json", ...numberArg(params, "revision", "--revision")];
    case "novelos_present":
      return ["present", String(params["task_id"] ?? ""), "--json", ...rid];
    case "novelos_decide":
      // 白名单仅 task_id：decision/nonce/author_note/revision 绝不从模型参数落 argv（03 G0 负向）
      return ["decide", String(params["task_id"] ?? ""), "--json"];
    case "novelos_checkpoint":
      return ["checkpoint", "--json", ...rid];
    default:
      throw new Error(`未知工具：${name}`);
  }
}

function failureResult(handshake: Extract<Handshake, { ok: false }>) {
  return {
    content: [{ type: "text", text: translateEnvError(handshake.error.code) }],
    details: {
      ok: false,
      errors: [{ code: handshake.error.code, message: handshake.error.message, hint: handshake.error.hint }],
    },
  };
}

function envelopeText(result: CallResult, successText: string): string {
  if (result.envelope.ok) return successText;
  return envelopeErrorsText(result.envelope.errors);
}

/** 各工具成功摘要（作者语言；不暴露字段名/内部路径/hash——05 §7）。 */
function successText(name: string, result: CallResult): string {
  const data = (result.envelope.data ?? {}) as Record<string, unknown>;
  switch (name) {
    case "novelos_init":
      return `已初始化：${String(data["workspace_root"] ?? "")}`;
    case "novelos_status":
      return JSON.stringify(result.envelope.data, null, 2);
    case "novelos_next":
      return String(data["user_message"] ?? data["reason"] ?? "");
    case "novelos_open_task": {
      const head =
        data["resumed"] === true
          ? `已恢复任务 ${String(data["task_id"])}（继续创作；原始想法见返回值 original_brief，作者修改意见见 revision_guidance_ref）`
          : `已创建任务 ${String(data["task_id"])}`;
      return `${head}；staging: ${String(data["staging_path"])}，请先阅读 ${String(data["instructions_ref"])}`;
    }
    case "novelos_submit_candidate":
      return `候选已提交（rev-${String(data["candidate_revision"])}）。请调用 novelos_validate 校验。`;
    case "novelos_validate": {
      if (data["valid"] === true) return "校验通过。请调用 novelos_present 向作者呈现候选。";
      const errors = Array.isArray(data["errors"]) ? (data["errors"] as Array<Record<string, unknown>>) : [];
      return (
        errors
          .map((e) => `${String(e["message"] ?? "")}${e["hint"] ? `（${String(e["hint"])}）` : ""}`)
          .join("\n") || "校验未通过。"
      );
    }
    case "novelos_present":
      return "已向作者呈现候选。请调用 novelos_decide 由作者决定。";
    case "novelos_checkpoint":
      return `已保存检查点：${String(data["checkpoint_id"])}。`;
    default:
      return JSON.stringify(result.envelope.data);
  }
}

interface PendingDecision {
  candidate_revision: number;
  nonce: string;
}

/** novelos_decide 执行（04 §3.6 五步；05 §8.3 无 UI 守卫逐字）。 */
async function executeDecide(
  client: CoreClient,
  params: Record<string, unknown>,
  ctx: ExtensionContext,
) {
  const fail = (text: string, result?: CallResult) => ({
    content: [{ type: "text", text }],
    details: {
      ok: false,
      data: result?.envelope.data ?? null,
      errors: result?.envelope.errors ?? [],
      exitCode: result?.exitCode ?? -1,
    },
  });

  // 1. 守卫：只有真 TUI 经此工具产生 INTERACTIVE_UI 来源（02 §7.6）
  if (!(ctx.hasUI && ctx.mode === "tui")) {
    return fail("此操作需要交互式确认。请切换到 interactive 模式后重试。");
  }

  const taskId = String(params["task_id"] ?? "");

  // 2. present 是变更命令：安全重试需 request-id（04 §1.5；同次 execute 传输重试复用该 ID）
  const presentRequestId = randomUUID();
  const present = await client.call(
    buildArgs("novelos_present", { task_id: taskId }, presentRequestId),
    { cwd: ctx.cwd },
  );
  if (!present.envelope.ok) return fail(envelopeErrorsText(present.envelope.errors), present);

  const data = (present.envelope.data ?? {}) as {
    present_packet?: PresentPacket;
    preview_content?: PreviewContentItem[];
    pending_decision?: PendingDecision;
  };
  const pending = data.pending_decision;
  if (pending === undefined) return fail("present 未返回待定决定。", present);

  // 3. 呈现 preview 全文 + packet 摘要（05 §3.1/§7），三选项
  const summary = renderDecidePreview(data.preview_content ?? [], data.present_packet ?? null);
  const choice = await ctx.ui.select(summary, [
    "ACCEPT（保存为正式版本）",
    "REVISE（补充意见后重写）",
    "REJECT（丢弃草稿）",
  ]);
  if (choice === undefined) return fail("作者取消了决定；候选保持待定。");
  const decision = choice.startsWith("ACCEPT")
    ? "ACCEPT"
    : choice.startsWith("REVISE")
      ? "REVISE"
      : "REJECT";

  // 4. REVISE/REJECT 收集作者意见
  let authorNote: string | undefined;
  if (decision !== "ACCEPT") {
    const note = await ctx.ui.input(
      decision === "REVISE" ? "作者修改意见（将进入下一轮创作任务）" : "终止原因（可选）",
      "",
    );
    authorNote = note !== undefined && note.trim() !== "" ? note : undefined;
  }

  // 5. decide：revision/nonce 取自 pending（不暴露给模型）；decide 一次性，无 request-id
  const decideArgs = [
    "decide",
    taskId,
    "--revision",
    String(pending.candidate_revision),
    "--nonce",
    pending.nonce,
    "--decision",
    decision.toLowerCase(),
    ...(authorNote !== undefined ? ["--author-note", authorNote] : []),
    "--json",
  ];
  const result = await client.call(decideArgs, { cwd: ctx.cwd });
  if (!result.envelope.ok) return fail(envelopeErrorsText(result.envelope.errors), result);

  const decided = (result.envelope.data ?? {}) as Record<string, unknown>;
  let text: string;
  if (decision === "ACCEPT") {
    text = "已接受：premise@1（story/premise.md 已正式落盘）";
  } else if (decision === "REVISE") {
    const note = typeof decided["author_note"] === "string" ? decided["author_note"] : (authorNote ?? "");
    const guidance =
      typeof decided["revision_guidance_ref"] === "string" ? decided["revision_guidance_ref"] : "";
    text = `已记录修改意见：「${note}」。请重读 .novelos/tasks/${taskId}/instructions.md 与 ${guidance} 后生成新候选。`;
  } else {
    text = "已终止任务。";
  }
  return {
    content: [{ type: "text", text }],
    details: { ok: true, data: result.envelope.data, errors: [], exitCode: result.exitCode },
  };
}

/** 每次调用生成 request-id 的变更动词（04 §1.5；validate 幂等、decide 一次性，不在其列）。 */
const REQUEST_ID_TOOLS = new Set([
  "novelos_init",
  "novelos_open_task",
  "novelos_submit_candidate",
  "novelos_present",
  "novelos_checkpoint",
]);

export function registerNovelosTools(
  pi: ExtensionAPI,
  client: CoreClient,
  getHandshake: HandshakeGetter,
): void {
  for (const def of NOVELOS_TOOL_DEFS) {
    pi.registerTool({
      name: def.name,
      label: def.label,
      description: def.description,
      promptSnippet: def.promptSnippet,
      parameters: def.parameters,
      async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
        const hs = await getHandshake();
        if (!hs.ok) return failureResult(hs);
        // schema 校验后的工具参数（Static<TSchema>）；白名单在 buildArgs 内二次收口
        const typedParams = params as Record<string, unknown>;
        if (def.name === "novelos_decide") {
          return await executeDecide(client, typedParams, ctx);
        }
        const requestId = REQUEST_ID_TOOLS.has(def.name) ? randomUUID() : undefined;
        const result = await client.call(buildArgs(def.name, typedParams, requestId), {
          cwd: ctx.cwd,
        });
        return {
          content: [{ type: "text", text: envelopeText(result, successText(def.name, result)) }],
          details: {
            ok: result.envelope.ok,
            data: result.envelope.data,
            errors: result.envelope.errors,
            exitCode: result.exitCode,
          },
        };
      },
    });
  }
}
