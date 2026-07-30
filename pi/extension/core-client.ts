/**
 * NovelOS Core launcher 客户端（薄适配，冻结文档 02 §6.3：零领域逻辑）。
 *
 * 发现链（冻结文档 04 §1.1，r6 定稿；r7 故障分类 + 依赖注入测试面）：
 *   1. 环境变量 NOVELOS_CORE（命令串，空白切分为 argv；不支持引号，含空格路径走 launcher.json）——显式候选
 *   2. ~/.novelos/launcher.json（安装脚本写入 {"argv": [...]}；NOVELOS_HOME 覆盖家目录）——显式候选
 *   3. PATH 中的 novelos console script——隐式候选（strict 模式排除）
 *   4. python -m novelos——隐式候选（strict 模式排除）
 *
 * 故障分类：ENOENT / 隐式候选 No module named novelos → 穿透下一候选；
 * 候选产生进程但输出无 JSON/不可解析 → CoreProtocolError → call 映射为
 * INTERNAL_ERROR 信封（绝不误报 CORE_LAUNCHER_NOT_FOUND）；全部候选失败 →
 * CORE_LAUNCHER_NOT_FOUND（退出码 5 语义，05 §6.1 转译入口）。
 *
 * 构造器 CoreDiscoveryOptions 全部可选，生产用缺省；测试经 DI 隔离（不碰进程 env）。
 * NOVELOS_HOME / NOVELOS_CORE_STRICT 为测试/诊断旋钮，只影响 NovelOS 自有发现链。
 */
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export const PROTOCOL_VERSION = "1.0";

export interface Envelope {
  ok: boolean;
  data: unknown;
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

/** 候选产生进程但输出不构成信封（协议错误）——call 映射为 INTERNAL_ERROR，不穿透。 */
export class CoreProtocolError extends Error {
  detail: string;

  constructor(message: string, detail: string) {
    super(message);
    this.name = "CoreProtocolError";
    this.detail = detail;
  }
}

/** 候选不可用（ENOENT / 隐式候选缺模块）——穿透下一候选。 */
class CandidateUnavailable extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CandidateUnavailable";
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

/** 发现链依赖注入选项（全部可选；生产用缺省，测试经构造器隔离）。 */
export interface CoreDiscoveryOptions {
  env?: NodeJS.ProcessEnv;
  /** 家目录覆盖；缺省 env NOVELOS_HOME → homedir()。 */
  home?: string;
  /** 显式覆盖 NOVELOS_CORE 命令串；null = 无 env 候选。 */
  envCommand?: string | null;
  /** launcher.json 路径覆盖；null = 禁用 launcher 候选。 */
  launcherConfigPath?: string | null;
  /** PATH 探测函数；缺省恒返回 name（交给 spawn 解析）。 */
  pathLookup?: (name: string) => string | null;
  /** 隐式 python 候选 argv 列表；缺省 [["python", "-m", "novelos"]]。 */
  pythonCandidates?: string[][];
  /** 严格模式：排除全部隐式候选；缺省 env NOVELOS_CORE_STRICT === "1"。 */
  strict?: boolean;
}

interface Candidate {
  argv: string[];
  implicit: boolean;
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
  private envCommand: string | null;
  private launcherConfigPath: string | null;
  private pathLookup: (name: string) => string | null;
  private pythonCandidates: string[][];
  private strict: boolean;

  constructor(opts?: CoreDiscoveryOptions) {
    this.env = opts?.env ?? process.env;
    this.home = opts?.home ?? this.env["NOVELOS_HOME"] ?? homedir();
    this.envCommand =
      opts?.envCommand !== undefined ? opts.envCommand : (this.env["NOVELOS_CORE"] ?? null);
    this.launcherConfigPath =
      opts?.launcherConfigPath !== undefined
        ? opts.launcherConfigPath
        : join(this.home, ".novelos", "launcher.json");
    this.pathLookup = opts?.pathLookup ?? ((name) => name);
    this.pythonCandidates = opts?.pythonCandidates ?? [["python", "-m", "novelos"]];
    this.strict = opts?.strict ?? this.env["NOVELOS_CORE_STRICT"] === "1";
  }

  /** 按优先序返回候选（04 §1.1 r6 发现链；strict 排除隐式候选）。 */
  async discover(): Promise<Candidate[]> {
    const candidates: Candidate[] = [];
    if (this.envCommand !== null && this.envCommand.trim().length > 0) {
      candidates.push({ argv: this.envCommand.trim().split(/\s+/), implicit: false });
    }
    if (this.launcherConfigPath !== null) {
      try {
        const raw = await readFile(this.launcherConfigPath, "utf8");
        const launcher = JSON.parse(raw) as { argv?: unknown };
        if (
          Array.isArray(launcher.argv) &&
          launcher.argv.length > 0 &&
          launcher.argv.every((v) => typeof v === "string")
        ) {
          candidates.push({ argv: launcher.argv as string[], implicit: false });
        }
      } catch {
        // launcher.json 缺失或不可读 → 落到下一候选
      }
    }
    if (!this.strict) {
      const looked = this.pathLookup("novelos");
      if (looked !== null) candidates.push({ argv: [looked], implicit: true });
      for (const argv of this.pythonCandidates) {
        candidates.push({ argv, implicit: true });
      }
    }
    return candidates;
  }

  private spawnOne(
    argv: string[],
    args: string[],
    cwd: string | undefined,
    implicit: boolean,
  ): Promise<{ envelope: Envelope; exitCode: number }> {
    const { promise, resolve, reject } = Promise.withResolvers<{
      envelope: Envelope;
      exitCode: number;
    }>();
    const child = spawn(argv[0], [...argv.slice(1), ...args], {
      cwd,
      // 强制 Python Core 以 UTF-8 输出（Windows 代码页默认 cp936），与本侧 utf8 解码闭环
      env: { ...this.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    child.on("error", (err: unknown) => {
      if (isEnoent(err)) reject(new CandidateUnavailable("命令不存在（ENOENT）"));
      else reject(new CoreProtocolError(`候选启动失败：${String(err)}`, String(err)));
    });
    child.stdout.on("data", (d: Buffer) => {
      stdout += d.toString("utf8");
    });
    child.stderr.on("data", (d: Buffer) => {
      stderr += d.toString("utf8");
    });
    child.on("close", (code: number | null) => {
      const lines = stdout.split(/\r?\n/).filter((l) => l.trim().length > 0);
      if (lines.length === 0) {
        // 隐式 python 候选缺模块 → 视为「非 launcher」穿透；显式候选同征 → 协议错误不误报 NOT_FOUND
        if (/No module named novelos/.test(stderr)) {
          if (implicit) reject(new CandidateUnavailable("python 缺 novelos 模块"));
          else
            reject(
              new CoreProtocolError(
                "显式候选的 Python 缺少 novelos 模块",
                stderr.slice(0, 400),
              ),
            );
          return;
        }
        reject(
          new CoreProtocolError(
            `Core 无 JSON 输出（退出码 ${code}）`,
            stderr.slice(0, 400) || stdout.slice(0, 400),
          ),
        );
        return;
      }
      try {
        const envelope = JSON.parse(lines[lines.length - 1]) as Envelope;
        resolve({ envelope, exitCode: code ?? 0 });
      } catch (err) {
        reject(new CoreProtocolError(`Core 输出无法解析为信封：${String(err)}`, stdout.slice(0, 400)));
      }
    });
    return promise;
  }

  /** 按发现链逐个候选尝试（故障分类见模块注释）。 */
  async call(args: string[], opts?: { cwd?: string }): Promise<CallResult> {
    const candidates = await this.discover();
    let lastDetail = "";
    for (const { argv, implicit } of candidates) {
      try {
        const result = await this.spawnOne(argv, args, opts?.cwd, implicit);
        return { envelope: result.envelope, exitCode: result.exitCode, argv };
      } catch (err) {
        if (err instanceof CandidateUnavailable) {
          lastDetail = `${argv[0]}: ${err.message}`;
          continue;
        }
        if (err instanceof CoreProtocolError) {
          // 显式覆盖/launcher 候选的损坏输出绝不报 NOT_FOUND（r7 分类）
          return {
            envelope: {
              ok: false,
              data: null,
              errors: [
                {
                  code: "INTERNAL_ERROR",
                  message: "Core 输出无法解析（协议错误）",
                  hint: "运行 novelos doctor 或重新安装（python scripts/install.py）",
                },
              ],
            },
            exitCode: 3, // 04 §1.4 EXIT_INTERNAL
            argv,
          };
        }
        throw err;
      }
    }
    throw new CoreEnvError(
      "CORE_LAUNCHER_NOT_FOUND",
      `Python Core launcher 发现失败${lastDetail ? `（最后候选 ${lastDetail}）` : ""}`,
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
    // 协议错误信封（call 已分类）：以环境错误呈现，提示 doctor/重装而非版本数值
    const firstError = result.envelope.errors[0];
    if (!result.envelope.ok && firstError?.code === "INTERNAL_ERROR") {
      return {
        ok: false,
        error: new CoreEnvError(
          "CORE_VERSION_MISMATCH",
          firstError.message,
          firstError.hint ?? "运行 novelos doctor 或重新安装（python scripts/install.py）",
        ),
      };
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
