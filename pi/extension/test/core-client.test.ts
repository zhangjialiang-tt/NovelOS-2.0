/**
 * core-client 单测（node --test，原生 TS type-stripping）。
 *
 * 前置：仓库已 `uv sync`（.venv 内有可用 python -m novelos）。
 * 覆盖：发现链优先序与 ENOENT 穿透、CORE_LAUNCHER_NOT_FOUND 安装提示、
 * 握手 happy path 与协议不兼容（冻结文档 04 §1.1/§1.2）。
 */
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import process from "node:process";
import { test } from "node:test";

import { CoreClient, CoreEnvError, PROTOCOL_VERSION } from "../core-client.ts";

const repoRoot = process.cwd();
const venvPython =
  process.platform === "win32"
    ? join(repoRoot, ".venv", "Scripts", "python.exe")
    : join(repoRoot, ".venv", "bin", "python");

async function tempHome(): Promise<string> {
  return await mkdtemp(join(tmpdir(), "novelos-home-"));
}

test("discovery: bogus NOVELOS_CORE falls through (ENOENT) to launcher.json", async () => {
  const home = await tempHome();
  try {
    await mkdir(join(home, ".novelos"), { recursive: true });
    await writeFile(
      join(home, ".novelos", "launcher.json"),
      JSON.stringify({ argv: [venvPython, "-m", "novelos"] }),
      "utf8",
    );
    const client = new CoreClient({
      env: { NOVELOS_CORE: "definitely-not-a-real-cmd-xyz", PATH: process.env.PATH ?? "" },
      home,
    });
    const result = await client.call(["version", "--json"]);
    assert.equal(result.exitCode, 0);
    assert.equal(result.envelope.ok, true);
    assert.equal(result.envelope.data.protocol_version, PROTOCOL_VERSION);
    // 命中的是 launcher.json 候选，不是 bogus env
    assert.deepEqual(result.argv, [venvPython, "-m", "novelos"]);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("discovery: nothing anywhere → CORE_LAUNCHER_NOT_FOUND with install hint", async () => {
  const home = await tempHome();
  try {
    const client = new CoreClient({
      env: { NOVELOS_CORE: "definitely-not-a-real-cmd-xyz", PATH: "" },
      home,
    });
    await assert.rejects(
      () => client.call(["version", "--json"]),
      (err: unknown) =>
        err instanceof CoreEnvError &&
        err.code === "CORE_LAUNCHER_NOT_FOUND" &&
        /install\.py/.test(err.hint),
    );
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("handshake: happy path returns ok with protocol 1.x", async () => {
  const home = await tempHome();
  try {
    const client = new CoreClient({
      env: { NOVELOS_CORE: `${venvPython} -m novelos`, PATH: process.env.PATH ?? "" },
      home,
    });
    const hs = await client.handshake("0.1.0");
    assert.equal(hs.ok, true);
    if (hs.ok) {
      assert.equal(hs.protocolVersion, PROTOCOL_VERSION);
      assert.ok(hs.coreVersion.length > 0);
      assert.equal(hs.upgradeHint, null);
    }
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("handshake: protocol major mismatch → CORE_VERSION_MISMATCH", async () => {
  const home = await tempHome();
  try {
    const stub = join(home, "stub-core.py");
    await writeFile(
      stub,
      [
        "import json",
        'print(json.dumps({"ok": True, "data": {"core_version": "9.9.9",',
        '      "protocol_version": "2.0", "min_extension_version": "0.1.0"}, "errors": []}))',
        "",
      ].join("\n"),
      "utf8",
    );
    const client = new CoreClient({
      env: { NOVELOS_CORE: `${venvPython} ${stub}`, PATH: process.env.PATH ?? "" },
      home,
    });
    const hs = await client.handshake("0.1.0");
    assert.equal(hs.ok, false);
    if (!hs.ok) assert.equal(hs.error.code, "CORE_VERSION_MISMATCH");
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("handshake: upgrade hint when extension below min_extension_version", async () => {
  const home = await tempHome();
  try {
    const stub = join(home, "stub-core2.py");
    await writeFile(
      stub,
      [
        "import json",
        'print(json.dumps({"ok": True, "data": {"core_version": "0.9.0",',
        '      "protocol_version": "1.0", "min_extension_version": "0.5.0"}, "errors": []}))',
        "",
      ].join("\n"),
      "utf8",
    );
    const client = new CoreClient({
      env: { NOVELOS_CORE: `${venvPython} ${stub}`, PATH: process.env.PATH ?? "" },
      home,
    });
    const hs = await client.handshake("0.1.0");
    assert.equal(hs.ok, true);
    if (hs.ok) assert.ok(hs.upgradeHint !== null && hs.upgradeHint.includes("0.5.0"));
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

// homedir() 默认路径烟雾：构造不抛错（不实际调用用户环境）
test("constructor defaults do not throw", () => {
  const client = new CoreClient();
  assert.equal(typeof client.home, "string");
  assert.equal(client.home, homedir());
});
