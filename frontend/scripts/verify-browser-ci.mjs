import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { runBrowserCi } from "./check-browser-ci.mjs";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const backendRoot = fileURLToPath(new URL("../../backend/", import.meta.url));
const nodePin = readFileSync(
  resolve(frontendRoot, ".node-version"),
  "utf8",
).trim();
const pythonPin = readFileSync(
  resolve(backendRoot, ".python-version"),
  "utf8",
).trim();
const pnpmPin = JSON.parse(
  readFileSync(resolve(frontendRoot, "package.json"), "utf8"),
)
  .packageManager.slice("pnpm@".length)
  .split("+")[0];

function recordingRunner({
  failAt,
  errorAt,
  nodeVersion = `v${nodePin}`,
  pnpmVersion = pnpmPin,
  pythonVersion = pythonPin,
} = {}) {
  const calls = [];
  const logs = [];
  function spawn(command, args, options) {
    calls.push({ command, args, ...options });
    if (calls.length === errorAt) return { error: new Error("spawn failed") };
    if (calls.length === failAt) return { status: 7 };
    let stdout = "";
    if (args[0] === "--version") {
      stdout = command === "pnpm" ? `${pnpmVersion}\n` : "uv 0.11.14\n";
    } else if (args[0] === "-c") {
      stdout = JSON.stringify({
        python: pythonVersion,
        playwright: "1.59.0",
        chromium: "147.0.7727.15",
        unwanted: "not runtime metadata",
      });
    }
    return { status: 0, stdout };
  }
  return {
    calls,
    logs,
    spawn,
    log: (message) => logs.push(message),
    nodeVersion,
  };
}

test("browser CI builds and runs every CI stage with explicit modes", () => {
  const runner = recordingRunner();

  runBrowserCi({ ...runner, environment: {} });

  const stages = runner.calls.slice(3);
  const resultsRoot = runner.logs[0].replace("Browser CI results: ", "");
  assert.equal(dirname(resultsRoot), resolve(backendRoot, "test-results"));
  assert.match(
    basename(resultsRoot),
    /^browser-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z-\d+$/,
  );
  assert.ok(resultsRoot.endsWith(`-${process.pid}`));
  assert.equal(stages.length, 5);
  assert.deepEqual(
    stages.map(({ command, args }) => [command, ...args]),
    [
      ["pnpm", "build", "--manifest"],
      [
        "uv",
        "run",
        "--locked",
        "pytest",
        "tests/e2e/test_production_frontend.py",
        "-q",
        `--junitxml=${resolve(resultsRoot, "production.xml")}`,
      ],
      [
        "uv",
        "run",
        "--locked",
        "pytest",
        "tests/e2e/test_editor_chunk_recovery.py",
        "-q",
        `--junitxml=${resolve(resultsRoot, "editor-chunk-recovery.xml")}`,
      ],
      [
        "uv",
        "run",
        "--locked",
        "pytest",
        "tests/e2e",
        "-m",
        "browser_smoke",
        "-n",
        "2",
        "--dist",
        "loadscope",
        "--max-worker-restart=0",
        "--strict-markers",
        "--maxfail=1",
        "--durations=10",
        "-v",
        `--junitxml=${resolve(resultsRoot, "browser-smoke.xml")}`,
      ],
      [
        "uv",
        "run",
        "--locked",
        "pytest",
        "tests/e2e/test_pdf_ats.py",
        "-q",
        `--junitxml=${resolve(resultsRoot, "pdf-ats.xml")}`,
      ],
    ],
  );
  assert.deepEqual(
    stages.map((stage) => stage.cwd),
    [frontendRoot, backendRoot, backendRoot, backendRoot, backendRoot],
  );
  assert.deepEqual(
    stages.map((stage) => stage.env.E2E_FRONTEND_MODE),
    ["dev", "preview", "preview", "dev", "dev"],
  );
  for (const call of runner.calls) {
    assert.equal(call.env.CI, "true");
    assert.equal(call.env.TZ, "UTC");
    assert.equal(call.env.RUN_BROWSER_E2E, "1");
    assert.equal(call.env.E2E_FRONTEND_DIST_DIR, resolve(frontendRoot, "dist"));
    assert.equal(call.env.E2E_ARTIFACTS_DIR, resolve(resultsRoot, "browser"));
  }
});

for (const [tool, key, version] of [
  ["Node", "nodeVersion", "v26.0.0"],
  ["pnpm", "pnpmVersion", "10.0.0"],
  ["Python", "pythonVersion", "3.13.3"],
]) {
  test(`browser CI rejects an unpinned ${tool} before building`, () => {
    const runner = recordingRunner({ [key]: version });

    assert.throws(
      () => runBrowserCi({ ...runner, environment: {} }),
      (error) =>
        error.message.includes(`${tool} ${version.replace(/^v/, "")}`) &&
        error.message.includes("required") &&
        error.message.includes("pnpm test:browser:linux"),
    );

    assert.equal(runner.calls.length, 3);
    assert.ok(!runner.calls.some(({ args }) => args.includes("build")));
    assert.ok(!runner.calls.some(({ args }) => args.includes("pytest")));
  });
}

for (const failAt of [1, 2, 3, 4, 5, 6, 7, 8]) {
  test(`browser CI stops immediately when command ${failAt} fails`, () => {
    const runner = recordingRunner({ failAt });

    assert.throws(
      () => runBrowserCi({ ...runner, environment: {} }),
      (error) => error.exitCode === 7,
    );

    assert.equal(runner.calls.length, failAt);
  });
}

test("browser CI stops after a subprocess cannot start", () => {
  const runner = recordingRunner({ errorAt: 5 });

  assert.throws(
    () => runBrowserCi({ ...runner, environment: {} }),
    /spawn failed/,
  );

  assert.equal(runner.calls.length, 5);
});

test("browser CI isolates overrides and logs only runtime versions", () => {
  const overrides = [
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE",
    "PDF_RENDER_TIMEOUT_MS",
    "PDFTOTEXT_EXECUTABLE",
    "PDF_ATS_OUTPUT_DIR",
    "E2E_CONTAINER_IMAGE",
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "RESENO_VITE_CACHE_DIR",
    "VITE_DEV_API_TARGET",
    "UV_PYTHON",
    "UV_PROJECT_ENVIRONMENT",
    "UV_PROJECT",
    "UV_NO_SYNC",
    "UV_FROZEN",
    "UV_CONFIG_FILE",
    "UV_ENV_FILE",
    "PYTHONPATH",
    "PYTHONHOME",
  ];
  const artifacts = resolve(backendRoot, "test-results/custom-browser");
  const environment = {
    ...Object.fromEntries(overrides.map((key) => [key, "external override"])),
    E2E_FRONTEND_MODE: "incorrect",
    E2E_FRONTEND_DIST_DIR: "/outdated/build",
    RUN_BROWSER_E2E: "0",
    E2E_ARTIFACTS_DIR: artifacts,
    PATH: "/toolchain/bin",
    UV_CACHE_DIR: "/isolated/uv-cache",
    CI: "false",
    TZ: "Asia/Taipei",
    RESENO_MASTER_KEY: "must-not-be-logged",
  };
  const original = { ...environment };
  const runner = recordingRunner();

  runBrowserCi({ ...runner, environment });

  assert.deepEqual(environment, original);
  for (const call of runner.calls) {
    for (const key of overrides) assert.equal(call.env[key], undefined, key);
    assert.equal(call.env.PATH, "/toolchain/bin");
    assert.equal(call.env.UV_CACHE_DIR, "/isolated/uv-cache");
    assert.equal(call.env.CI, "true");
    assert.equal(call.env.TZ, "UTC");
    assert.equal(call.env.E2E_ARTIFACTS_DIR, artifacts);
    assert.equal(call.env.RUN_BROWSER_E2E, "1");
    assert.equal(call.env.E2E_FRONTEND_DIST_DIR, resolve(frontendRoot, "dist"));
  }
  const runtime = JSON.parse(
    runner.logs
      .find((line) => line.startsWith("Browser CI runtime: "))
      .replace("Browser CI runtime: ", ""),
  );
  assert.equal(runtime.node, `v${nodePin}`);
  assert.equal(runtime.pnpm, pnpmPin);
  assert.equal(runtime.uv, "uv 0.11.14");
  assert.equal(runtime.python, pythonPin);
  assert.equal(runtime.playwright, "1.59.0");
  assert.equal(runtime.chromium, "147.0.7727.15");
  assert.ok(runtime.os && runtime.osRelease && runtime.arch);
  assert.equal(runtime.unwanted, undefined);
  assert.ok(!runner.logs.join("\n").includes("must-not-be-logged"));
});
