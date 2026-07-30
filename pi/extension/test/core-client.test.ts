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
import { handshakeFailure } from "../ui.ts";

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
    if (!hs.ok) {
      assert.equal(hs.kind, "ENVIRONMENT");
      if (hs.kind === "ENVIRONMENT") assert.equal(hs.error.code, "CORE_VERSION_MISMATCH");
    }
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

test("UTF-8 round-trip: Chinese user_message survives spawn→decode (Windows regression)", async () => {
  const home = await tempHome();
  const novel = await mkdtemp(join(tmpdir(), "novelos-ws-"));
  try {
    const client = new CoreClient({
      env: { NOVELOS_CORE: `${venvPython} -m novelos`, PATH: process.env.PATH ?? "" },
      home,
    });
    const result = await client.call(["next", "--json"], { cwd: novel });
    assert.equal(result.exitCode, 0);
    assert.equal(result.envelope.ok, true);
    assert.equal(result.envelope.data.reason_code, "NOT_INITIALIZED");
    assert.equal(result.envelope.data.user_message, "还没有作品。要开始新故事吗？");
  } finally {
    await rm(home, { recursive: true, force: true });
    await rm(novel, { recursive: true, force: true });
  }
});

const demoWs = process.env.NOVELOS_DEMO_WS;

test(
  "real workspace: initialized next carries intact Chinese user_message",
  { skip: !demoWs ? "set NOVELOS_DEMO_WS to a real initialized workspace to run" : false },
  async () => {
    const home = await tempHome();
    try {
      const client = new CoreClient({
        env: { NOVELOS_CORE: `${venvPython} -m novelos`, PATH: process.env.PATH ?? "" },
        home,
      });
      const status = await client.call(["status", "--json"], { cwd: demoWs });
      assert.equal(status.envelope.ok, true);
      assert.equal(status.envelope.data.initialized, true);
      const next = await client.call(["next", "--json"], { cwd: demoWs });
      assert.equal(next.envelope.ok, true);
      assert.equal(next.envelope.data.reason_code, "PREMISE_READY");
      assert.equal(next.envelope.data.user_message, "下一步：确定故事核心（创建 Story Brief）。");
    } finally {
      await rm(home, { recursive: true, force: true });
    }
  },
);

// ---------------------------------------------------------------------------
// D1：发现链依赖注入 + 故障分类（r7：NOT_FOUND vs 协议错误，经构造器 DI 不碰进程 env）
// ---------------------------------------------------------------------------

test("discovery DI: bogus envCommand falls through to valid launcherConfigPath", async () => {
  const home = await tempHome();
  try {
    const launcherPath = join(home, "launcher.json");
    await writeFile(launcherPath, JSON.stringify({ argv: [venvPython, "-m", "novelos"] }), "utf8");
    const client = new CoreClient({
      env: {},
      envCommand: "definitely-not-a-real-cmd-xyz",
      launcherConfigPath: launcherPath,
      strict: true,
    });
    const result = await client.call(["version", "--json"]);
    assert.equal(result.envelope.ok, true);
    assert.deepEqual(result.argv, [venvPython, "-m", "novelos"]);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("classification: explicit candidate corrupt output → INTERNAL_ERROR, no fall-through", async () => {
  const home = await tempHome();
  try {
    // 显式 launcher 候选输出非 JSON（argv 数组经 launcher.json，避免命令串空白切分）
    const launcherPath = join(home, "launcher.json");
    await writeFile(
      launcherPath,
      JSON.stringify({ argv: [venvPython, "-c", "print('garbage')"] }),
      "utf8",
    );
    const client = new CoreClient({
      env: {},
      envCommand: null,
      launcherConfigPath: launcherPath,
      // 即使隐式候选健康，协议错误也必须停链而非穿透
      pythonCandidates: [[venvPython, "-m", "novelos"]],
      strict: false,
    });
    const result = await client.call(["version", "--json"]);
    assert.equal(result.envelope.ok, false);
    assert.equal(result.envelope.errors[0].code, "INTERNAL_ERROR");
    assert.match(result.envelope.errors[0].message, /协议错误/);
    assert.match(result.envelope.errors[0].hint ?? "", /doctor/);
    // 命中的是损坏的显式候选（绝不误报 NOT_FOUND，也不穿透到健康隐式候选）
    assert.deepEqual(result.argv, [venvPython, "-c", "print('garbage')"]);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("classification: implicit candidate missing module → falls through to next", async () => {
  const home = await tempHome();
  try {
    const client = new CoreClient({
      env: {},
      envCommand: "definitely-not-a-real-cmd-xyz",
      launcherConfigPath: null,
      pathLookup: () => null,
      pythonCandidates: [
        [venvPython, "-c", "import sys;sys.stderr.write('No module named novelos\\n');sys.exit(1)"],
        [venvPython, "-m", "novelos"],
      ],
      strict: false,
    });
    const result = await client.call(["version", "--json"]);
    assert.equal(result.envelope.ok, true);
    assert.deepEqual(result.argv, [venvPython, "-m", "novelos"]);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("classification: everything gone → CORE_LAUNCHER_NOT_FOUND + install hint", async () => {
  const home = await tempHome();
  try {
    const client = new CoreClient({
      env: {},
      envCommand: "definitely-not-a-real-cmd-xyz",
      launcherConfigPath: join(home, "absent", "launcher.json"),
      pathLookup: () => null,
      pythonCandidates: [],
      strict: false,
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

test("classification: valid JSON but invalid envelope shape → INTERNAL_ERROR (no TypeError)", async () => {
  const home = await tempHome();
  try {
    const payloads = [
      "{}",
      "[]",
      '{"ok":true,"data":{}}',
      '{"ok":"true","data":{},"errors":[]}',
      '{"ok":false,"data":null,"errors":[{}]}',
    ];
    for (const payload of payloads) {
      const stub = join(home, "shape-stub.py");
      await writeFile(stub, `print(${JSON.stringify(payload)})\n`, "utf8");
      const launcherPath = join(home, "launcher.json");
      await writeFile(launcherPath, JSON.stringify({ argv: [venvPython, stub] }), "utf8");
      const client = new CoreClient({
        env: {},
        envCommand: null,
        launcherConfigPath: launcherPath,
        strict: true,
      });
      const result = await client.call(["version", "--json"]);
      assert.equal(result.envelope.ok, false, `payload ${payload} 应失败`);
      assert.equal(result.envelope.errors[0]?.code, "INTERNAL_ERROR", `payload ${payload}`);
      assert.match(result.envelope.errors[0]?.message ?? "", /协议错误/, `payload ${payload}`);
    }
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("handshake: protocol corruption surfaces PROTOCOL kind, never version mismatch", async () => {
  const home = await tempHome();
  try {
    const stub = join(home, "corrupt-handshake.py");
    await writeFile(stub, "print('{}')\n", "utf8");
    const launcherPath = join(home, "launcher.json");
    await writeFile(launcherPath, JSON.stringify({ argv: [venvPython, stub] }), "utf8");
    const client = new CoreClient({
      env: {},
      envCommand: null,
      launcherConfigPath: launcherPath,
      strict: true,
    });
    const hs = await client.handshake("0.1.0");
    assert.equal(hs.ok, false);
    if (!hs.ok) {
      assert.equal(hs.kind, "PROTOCOL");
      if (hs.kind === "PROTOCOL") {
        const failure = handshakeFailure(hs);
        assert.match(failure.text, /核心组件响应异常/);
        assert.ok(!failure.text.includes("版本不兼容"), "协议损坏不得呈现为版本不兼容");
        assert.equal(failure.errors[0]?.code, "INTERNAL_ERROR");
      }
    }
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("handshake: discovery failure surfaces ENVIRONMENT kind", async () => {
  const home = await tempHome();
  try {
    const client = new CoreClient({
      env: {},
      envCommand: "definitely-not-a-real-cmd-xyz",
      launcherConfigPath: join(home, "absent", "launcher.json"),
      pathLookup: () => null,
      pythonCandidates: [],
      strict: false,
    });
    const hs = await client.handshake("0.1.0");
    assert.equal(hs.ok, false);
    if (!hs.ok) {
      assert.equal(hs.kind, "ENVIRONMENT");
      if (hs.kind === "ENVIRONMENT") assert.equal(hs.error.code, "CORE_LAUNCHER_NOT_FOUND");
    }
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});
