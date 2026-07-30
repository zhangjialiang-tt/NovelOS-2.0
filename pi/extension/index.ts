/**
 * NovelOS Extension 入口（冻结文档 02 §6.1）。
 *
 * 默认导出同步工厂：只注册，不启动后台资源（官方告诫，冻结文档 02 §3.2）。
 * 版本握手在 session_start 执行并缓存；命令/工具懒加载兜底（冻结文档 04 §1.2）。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { CoreClient, type Handshake } from "./core-client.ts";
import { registerNovelosCommands } from "./commands.ts";
import { registerNovelosTools } from "./tools.ts";

export const EXTENSION_VERSION = "0.1.0";

export default function (pi: ExtensionAPI): void {
  const client = new CoreClient();
  let handshake: Handshake | null = null;
  let pending: Promise<Handshake> | null = null;

  const getHandshake = async (): Promise<Handshake> => {
    if (handshake !== null) return handshake;
    if (pending === null) {
      pending = client.handshake(EXTENSION_VERSION).finally(() => {
        pending = null;
      });
    }
    handshake = await pending;
    return handshake;
  };

  pi.on("session_start", async () => {
    handshake = await getHandshake();
  });

  registerNovelosTools(pi, client, getHandshake);
  registerNovelosCommands(pi, client, getHandshake);
}
