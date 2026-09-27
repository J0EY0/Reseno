import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { arch, platform, release } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const backendRoot = fileURLToPath(new URL("../../backend/", import.meta.url));
const projectPython = resolve(
  backendRoot,
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python",
);
const runtimeProbe = `
import importlib.metadata
import json
import sys
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        print(json.dumps({
            "python": sys.version.split()[0],
            "playwright": importlib.metadata.version("playwright"),
            "chromium": browser.version,
        }))
    finally:
        browser.close()
`;

export function runBrowserCi({
  spawn = spawnSync,
  environment = process.env,
  log = console.log,
  nodeVersion = process.version,
  args = [],
} = {}) {
  let shard;
  if (args.length > 0) {
    const match =
      args.length === 2 &&
      args[0] === "--shard" &&
      /^([1-9]\d*)\/([1-9]\d*)$/.exec(args[1]);
    if (!match) throw new Error("Expected --shard INDEX/TOTAL.");
    const index = Number(match[1]);
    const total = Number(match[2]);
    if (
      !Number.isSafeInteger(index) ||
      !Number.isSafeInteger(total) ||
      index > total
    ) {
      throw new Error("Invalid shard: INDEX must be between 1 and TOTAL.");
    }
    shard = { index, total };
  }
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const resultsRoot = resolve(
    backendRoot,
    "test-results",
    `browser-${timestamp}-${process.pid}`,
  );
  log(`Browser CI results: ${resultsRoot}`);
  const splitArgs = [];
  if (shard) {
    const durationsPath = resolve(resultsRoot, "split-durations.json");
    mkdirSync(resultsRoot, { recursive: true });
    writeFileSync(durationsPath, "{}\n");
    splitArgs.push(
      "--splits",
      String(shard.total),
      "--group",
      String(shard.index),
      "--splitting-algorithm",
      "duration_based_chunks",
      "--durations-path",
      durationsPath,
    );
    log(`Browser CI shard: ${shard.index}/${shard.total}`);
  }
  const env = { ...environment };
  for (const key of [
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
  ]) {
    delete env[key];
  }
  env.CI = "true";
  env.TZ = "UTC";
  env.RUN_BROWSER_E2E = "1";
  env.E2E_FRONTEND_MODE = "dev";
  env.E2E_FRONTEND_DIST_DIR = resolve(frontendRoot, "dist");
  env.E2E_ARTIFACTS_DIR = resolve(
    env.E2E_ARTIFACTS_DIR || resolve(resultsRoot, "browser"),
  );

  function run(label, command, args, options = {}) {
    const result = spawn(command, args, {
      cwd: backendRoot,
      env,
      stdio: "inherit",
      ...options,
    });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      const error = new Error(
        `${label} failed (${result.signal ?? `exit ${result.status ?? 1}`}).`,
      );
      error.exitCode = result.status || 1;
      throw error;
    }
    return result.stdout?.trim();
  }

  const probeOptions = {
    stdio: ["ignore", "pipe", "inherit"],
    encoding: "utf8",
  };
  const pnpm = run("Read pnpm version", "pnpm", ["--version"], {
    ...probeOptions,
    cwd: frontendRoot,
  });
  const uv = run("Read uv version", "uv", ["--version"], probeOptions);
  const browserRuntime = JSON.parse(
    run(
      "Inspect browser runtime",
      projectPython,
      ["-c", runtimeProbe],
      probeOptions,
    ),
  );
  log(
    `Browser CI runtime: ${JSON.stringify({
      os: platform(),
      osRelease: release(),
      arch: arch(),
      node: nodeVersion,
      pnpm,
      uv,
      python: browserRuntime.python,
      playwright: browserRuntime.playwright,
      chromium: browserRuntime.chromium,
    })}`,
  );
  const packageManager = JSON.parse(
    readFileSync(resolve(frontendRoot, "package.json"), "utf8"),
  ).packageManager;
  const versions = [
    [
      "Node",
      nodeVersion.replace(/^v/, ""),
      readFileSync(resolve(frontendRoot, ".node-version"), "utf8").trim(),
    ],
    ["pnpm", pnpm, packageManager.slice("pnpm@".length).split("+")[0]],
    [
      "Python",
      browserRuntime.python,
      readFileSync(resolve(backendRoot, ".python-version"), "utf8").trim(),
    ],
  ];
  const mismatches = versions
    .filter(([, actual, expected]) => actual !== expected)
    .map(
      ([tool, actual, expected]) => `${tool} ${actual} (required ${expected})`,
    );
  if (mismatches.length > 0) {
    throw new Error(
      `Browser CI toolchain mismatch: ${mismatches.join(", ")}. Use the repository-pinned versions or run pnpm test:browser:linux.`,
    );
  }

  const stages = [
    {
      label: "Build production frontend",
      command: "pnpm",
      args: ["build", "--manifest"],
      cwd: frontendRoot,
      mode: "dev",
      shared: true,
    },
    {
      label: "Test production frontend hosting",
      args: [
        "tests/e2e/test_production_frontend.py",
        "-q",
        `--junitxml=${resolve(resultsRoot, "production.xml")}`,
      ],
      mode: "preview",
      shared: true,
    },
    {
      label: "Test production editor chunk recovery",
      args: [
        "tests/e2e/test_editor_chunk_recovery.py",
        "-q",
        `--junitxml=${resolve(resultsRoot, "editor-chunk-recovery.xml")}`,
      ],
      mode: "preview",
      shared: true,
    },
    {
      label: "Run browser smoke tests",
      args: [
        "tests/e2e",
        "-m",
        "browser_smoke",
        ...splitArgs,
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
      mode: "dev",
    },
    {
      label: "Run PDF ATS tests",
      args: [
        "tests/e2e/test_pdf_ats.py",
        "-q",
        `--junitxml=${resolve(resultsRoot, "pdf-ats.xml")}`,
      ],
      mode: "dev",
      shared: true,
    },
  ];
  for (const stage of stages) {
    if (stage.shared && shard && shard.index !== 1) continue;
    log(stage.label);
    run(
      stage.label,
      stage.command ?? "uv",
      stage.command ? stage.args : ["run", "--locked", "pytest", ...stage.args],
      {
        cwd: stage.cwd ?? backendRoot,
        env: { ...env, E2E_FRONTEND_MODE: stage.mode },
      },
    );
  }
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    runBrowserCi({ args: process.argv.slice(2) });
  } catch (error) {
    console.error(error.message);
    process.exitCode = error.exitCode ?? 1;
  }
}
