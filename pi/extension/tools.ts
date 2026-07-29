/**
 * NovelOS 工具注册（冻结文档 04 §2：novelos_init / novelos_status / novelos_next）。
 *
 * 薄适配三件事（冻结文档 02 §6.3）：校验/转换参数 → 调用 Core launcher → 解析 JSON 映射为 tool result。
 * 幂等：novelos_init 每次调用生成 per-call UUID 作为 --request-id（冻结文档 04 §1.5），不暴露给模型。
 */
import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import type { CallResult, CoreClient, Handshake } from "./core-client.ts";
import { translateEnvError } from "./ui.ts";

type HandshakeGetter = () => Promise<Handshake>;

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
  return result.envelope.errors
    .map((e) => `${e.message}${e.hint ? `（${e.hint}）` : ""}`)
    .join("\n");
}

export function registerNovelosTools(pi: ExtensionAPI, client: CoreClient, getHandshake: HandshakeGetter): void {
  pi.registerTool({
    name: "novelos_init",
    label: "NovelOS 初始化",
    description: "把当前作品目录初始化为 NovelOS Workspace；未初始化时是唯一入口。",
    promptSnippet: "初始化 NovelOS 作品目录",
    parameters: Type.Object({
      project_name: Type.Optional(Type.String({ description: "项目名；缺省取目录名" })),
    }),
    async execute(_toolCallId, params: { project_name?: string }, _signal, _onUpdate, ctx) {
      const hs = await getHandshake();
      if (!hs.ok) return failureResult(hs);

      const requestId = randomUUID();
      const args = ["init", "--json", "--request-id", requestId];
      if (typeof params.project_name === "string" && params.project_name.trim() !== "") {
        args.push("--project-name", params.project_name);
      }
      const result = await client.call(args, { cwd: ctx.cwd });
      return {
        content: [
          {
            type: "text",
            text: envelopeText(result, `已初始化：${result.envelope.data?.workspace_root ?? ctx.cwd}`),
          },
        ],
        details: {
          ok: result.envelope.ok,
          data: result.envelope.data,
          errors: result.envelope.errors,
          exitCode: result.exitCode,
        },
      };
    },
  });

  pi.registerTool({
    name: "novelos_status",
    label: "NovelOS 状态",
    description: "查询作品状态板数据：阶段、已完成、当前问题、合法动作。只读。",
    promptSnippet: "查询 NovelOS 状态板",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      const hs = await getHandshake();
      if (!hs.ok) return failureResult(hs);
      const result = await client.call(["status", "--json"], { cwd: ctx.cwd });
      return {
        content: [{ type: "text", text: envelopeText(result, JSON.stringify(result.envelope.data, null, 2)) }],
        details: {
          ok: result.envelope.ok,
          data: result.envelope.data,
          errors: result.envelope.errors,
          exitCode: result.exitCode,
        },
      };
    },
  });

  pi.registerTool({
    name: "novelos_next",
    label: "NovelOS 下一步",
    description: "推导下一步建议动作与理由。只读，不创建任何对象。",
    promptSnippet: "获取 NovelOS 下一步建议",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      const hs = await getHandshake();
      if (!hs.ok) return failureResult(hs);
      const result = await client.call(["next", "--json"], { cwd: ctx.cwd });
      return {
        content: [
          {
            type: "text",
            text: envelopeText(result, `${result.envelope.data?.suggested_action}: ${result.envelope.data?.reason}`),
          },
        ],
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
