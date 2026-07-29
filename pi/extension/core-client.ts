/**
 * NovelOS Core launcher 客户端（薄适配，冻结文档 02 §6.3：零领域逻辑）。
 *
 * 发现链（冻结文档 04 §1.1，r6 定稿）：
 *   1. 环境变量 NOVELOS_CORE（命令串，空白切分为 argv；不支持引号，
 *      含空格路径请走 launcher.json）
 *   2. ~/.novelos/launcher.json（安装脚本写入 {"argv": [...]}）
 *   3. PATH 中的 novelos console script
 *   4. python -m novelos
 * 全部 ENOENT → CoreEnvError CORE_LAUNCHER_NOT_FOUND（冻结文档 04 §4，退出码 5 语义）。
 *
 * 纯 Node 实现、无 pi 依赖 → 可单测（pi/extension/test/core-client.test.ts）。
 */
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export const PROTOCOL_VERSION = "1.0";

export interface Envelope {
  ok: boolean;
  data: any;
  errors: Array<{ code: string; message: string; path?: string; hint?: string }>;
}

export class CoreEnvError extends Error {
  code: "CORE_LAUNCHER_NOT_FOUND" | "CORE_VERSION_MISMATCH";
  hint: string;

  constructor(code: "CORE_LAUNCHER_NOT_FOUND" | "CORE_VERSION_MISMATCH", message: string, hint: string) {
    super(message);
    this.name = "CoreEnvError";
    this.code = code;
    this.hint = hint;
  }
}

export type Handshake =
  | { ok: true; coreVersion: string; protocolVersion: string; upgradeHint: string | null }
  | { ok: false; error: CoreEnvError };

export interface CallResult {
  envelope: Envelope;
  exitCode: number;
  argv: string[];
}

function isEnoent(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { code?: unknown }).code === "ENOENT";
}

function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((n) => parseInt(n, 10) || 0);
  const pb = b.split(".").map((n) => parseInt(n, 10) || 0);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}

export class CoreClient {
  env: NodeJS.ProcessEnv;
  home: string;

  constructor(opts?: { env?: NodeJS.ProcessEnv; home?: string }) {
    this.env = opts?.env ?? process.env;
    this.home = opts?.home ?? homedir();
  }

  /** 按优先序返回候选 argv（04 §1.1 r6 发现链）。 */
  async discover(): Promise<string[][]> {
    const candidates: string[][] = [];
    const override = this.env["NOVELOS_CORE"];
    if (override && override.trim().length > 0) {
      candidates.push(override.trim().split(/\s+/));
    }
    try {
      const raw = await readFile(join(this.home, ".novelos", "launcher.json"), "utf8");
      const launcher = JSON.parse(raw) as { argv?: unknown };
      if (
        Array.isArray(launcher.argv) &&
        launcher.argv.length > 0 &&
        launcher.argv.every((v) => typeof v === "string")
      ) {
        candidates.push(launcher.argv as string[]);
      }
    } catch {
      // launcher.json 缺失或不可读 → 落到下一候选
    }
    candidates.push(["novelos"]);
    candidates.push(["python", "-m", "novelos"]);
    return candidates;
  }

  private spawnOne(
    argv: string[],
    args: string[],
    cwd?: string,
  ): Promise<{ envelope: Envelope; exitCode: number }> {
    return new Promise((resolve, reject) => {
      const child = spawn(argv[0], [...argv.slice(1), ...args], {
        cwd,
        env: this.env,
        windowsHide: true,
      });
      let stdout = "";
      let stderr = "";
      child.on("error", reject);
      child.stdout.on("data", (d: Buffer) => {
        stdout += d.toString("utf8");
      });
      child.stderr.on("data", (d: Buffer) => {
        stderr += d.toString("utf8");
      });
      child.on("close", (code: number | null) => {
        const lines = stdout.split(/\r?\n/).filter((l) => l.trim().length > 0);
        if (lines.length === 0) {
          reject(new Error(`Core 无 JSON 输出（退出码 ${code}）；stderr: ${stderr.slice(0, 400)}`));
          return;
        }
        try {
          const envelope = JSON.parse(lines[lines.length - 1]) as Envelope;
          resolve({ envelope, exitCode: code ?? 0 });
        } catch (err) {
          reject(new Error(`Core 输出无法解析为信封：${err}；原文：${stdout.slice(0, 400)}`));
        }
      });
    });
  }

  /** 按发现链逐个候选尝试；全部 ENOENT → CORE_LAUNCHER_NOT_FOUND（05 §6.1 转译入口）。 */
  async call(args: string[], opts?: { cwd?: string }): Promise<CallResult> {
    const candidates = await this.discover();
    for (const argv of candidates) {
      try {
        const result = await this.spawnOne(argv, args, opts?.cwd);
        return { envelope: result.envelope, exitCode: result.exitCode, argv };
      } catch (err) {
        if (isEnoent(err)) continue;
        throw err;
      }
    }
    throw new CoreEnvError(
      "CORE_LAUNCHER_NOT_FOUND",
      "Python Core launcher 发现失败",
      "运行安装脚本：python scripts/install.py",
    );
  }

  /** 版本握手（冻结文档 04 §1.2）：protocol 同主版本号视为兼容。 */
  async handshake(extensionVersion: string): Promise<Handshake> {
    let result: CallResult;
    try {
      result = await this.call(["version", "--json"]);
    } catch (err) {
      if (err instanceof CoreEnvError) return { ok: false, error: err };
      throw err;
    }
    const data = (result.envelope.data ?? {}) as Record<string, unknown>;
    const protocol = String(data.protocol_version ?? "");
    if (!result.envelope.ok || protocol.split(".")[0] !== PROTOCOL_VERSION.split(".")[0]) {
      return {
        ok: false,
        error: new CoreEnvError(
          "CORE_VERSION_MISMATCH",
          `协议版本不兼容：core protocol ${protocol || "?"} vs extension ${PROTOCOL_VERSION}`,
          "更新安装：python scripts/install.py",
        ),
      };
    }
    const min = String(data.min_extension_version ?? "0.0.0");
    return {
      ok: true,
      coreVersion: String(data.core_version ?? ""),
      protocolVersion: protocol,
      upgradeHint:
        compareVersions(extensionVersion, min) < 0
          ? `Extension 版本低于 Core 最低要求 ${min}，请更新扩展`
          : null,
    };
  }
}
