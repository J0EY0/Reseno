import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

const script = readFileSync(
  new URL("../../.github/scripts/check-browser-linux.sh", import.meta.url),
  "utf8",
);

for (const [testStatus, ownershipStatus, expectedStatus] of [
  [0, 0, 0],
  [7, 0, 7],
  [0, 1, 1],
  [7, 1, 7],
]) {
  test(`Linux browser artifacts return to the caller after test status ${testStatus} and ownership status ${ownershipStatus}`, () => {
    const root = mkdtempSync(resolve(tmpdir(), "reseno-browser-linux-"));
    try {
      mkdirSync(resolve(root, ".github/scripts"), { recursive: true });
      mkdirSync(resolve(root, "frontend"));
      mkdirSync(resolve(root, "bin"));
      writeFileSync(
        resolve(root, ".github/scripts/check-browser-linux.sh"),
        script,
      );
      writeFileSync(resolve(root, "frontend/.node-version"), "24.15.0\n");
      const commands = {
        docker: `#!/usr/bin/env bash
set -eu
command=$1
shift
if [ "$command" = build ]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --iidfile ]; then printf 'test-image' > "$2"; break; fi
    shift
  done
elif [ "$command" = run ]; then
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --env) export "$2"; shift 2 ;;
      --mount) shift 2 ;;
      --rm|--init|--ipc=host) shift ;;
      test-image)
        shift
        if [ "$#" -eq 0 ]; then set -- pnpm test:browser:ci; fi
        exec "$@"
        ;;
      *) exit 99 ;;
    esac
  done
fi
`,
        pnpm: `#!/usr/bin/env bash
printf '%s\\n' "$@" > "$TEST_COMMAND_LOG"
exit "$TEST_STATUS"
`,
        chown: `#!/usr/bin/env bash
printf '%s\\n' "$@" > "$OWNERSHIP_LOG"
exit "$OWNERSHIP_STATUS"
`,
      };
      for (const [name, source] of Object.entries(commands)) {
        const path = resolve(root, "bin", name);
        writeFileSync(path, source);
        chmodSync(path, 0o755);
      }
      const result = spawnSync(
        "bash",
        [".github/scripts/check-browser-linux.sh"],
        {
          cwd: root,
          encoding: "utf8",
          env: {
            ...process.env,
            PATH: `${resolve(root, "bin")}:${process.env.PATH}`,
            TEST_COMMAND_LOG: resolve(root, "command.log"),
            OWNERSHIP_LOG: resolve(root, "ownership.log"),
            TEST_STATUS: String(testStatus),
            OWNERSHIP_STATUS: String(ownershipStatus),
          },
        },
      );
      assert.equal(result.status, expectedStatus, result.stderr);
      assert.equal(
        readFileSync(resolve(root, "command.log"), "utf8"),
        "test:browser:ci\n",
      );
      assert.deepEqual(
        readFileSync(resolve(root, "ownership.log"), "utf8").trim().split("\n"),
        [
          "-R",
          "--no-dereference",
          `${process.getuid()}:${process.getgid()}`,
          "/workspace/backend/test-results",
        ],
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}
