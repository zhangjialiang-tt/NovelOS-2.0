/**
 * NovelOS 命令注册（冻结文档 05 §2.1）：
 *   /novelos         状态板 + 下一步建议（status + next）
 *   /novelos-status  纯状态板（仅 status，无建议动作栏）
 * /novelos-resume 属后续 Goal。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { CoreClient, Handshake } from "./core-client.ts";
import {
  renderNotInitialized,
  renderStatusBoard,
  translateEnvelopeError,
  translateEnvError,
  type NextData,
  type StatusData,
} from "./ui.ts";

type HandshakeGetter = () => Promise<Handshake>;

export function registerNovelosCommands(
  pi: ExtensionAPI,
  client: CoreClient,
  getHandshake: HandshakeGetter,
): void {
  pi.registerCommand("novelos", {
    description: "NovelOS 状态板 + 下一步建议",
    handler: async (_args, ctx) => {
      const hs = await getHandshake();
      if (!hs.ok) {
        ctx.ui.notify(translateEnvError(hs.error.code), "error");
        return;
      }
      const status = await client.call(["status", "--json"], { cwd: ctx.cwd });
      if (!status.envelope.ok) {
        ctx.ui.notify(translateEnvelopeError(status.envelope.errors), "error");
        return;
      }
      const statusData = status.envelope.data as StatusData;
      if (statusData.initialized === false) {
        ctx.ui.notify(renderNotInitialized(), "info");
        return;
      }
      const next = await client.call(["next", "--json"], { cwd: ctx.cwd });
      const nextData = next.envelope.ok ? (next.envelope.data as NextData) : null;
      ctx.ui.notify(renderStatusBoard(statusData, nextData), "info");
    },
  });

  pi.registerCommand("novelos-status", {
    description: "NovelOS 纯状态板（只读，无建议动作栏）",
    handler: async (_args, ctx) => {
      const hs = await getHandshake();
      if (!hs.ok) {
        ctx.ui.notify(translateEnvError(hs.error.code), "error");
        return;
      }
      const status = await client.call(["status", "--json"], { cwd: ctx.cwd });
      if (!status.envelope.ok) {
        ctx.ui.notify(translateEnvelopeError(status.envelope.errors), "error");
        return;
      }
      const statusData = status.envelope.data as StatusData;
      if (statusData.initialized === false) {
        ctx.ui.notify(renderNotInitialized(), "info");
        return;
      }
      ctx.ui.notify(renderStatusBoard(statusData, null), "info");
    },
  });
}
