import { readdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const filters = process.argv.slice(2).filter((value) => value !== "--");
const separateChecks = new Set([
  "verify-bundle-budgets.mjs",
  "verify-source-budgets.mjs",
]);
const files = (await readdir(new URL("./", import.meta.url)))
  .filter(
    (name) =>
      (name.startsWith("verify-") &&
        name.endsWith(".mjs") &&
        !separateChecks.has(name)) ||
      name === "generate-resume-edit-operation-types.mjs" ||
      name === "generate-template-presets.mjs",
  )
  .sort();
for (const filter of filters) {
  if (!files.some((file) => `scripts/${file}`.includes(filter))) {
    throw new Error(`No verification file matches ${JSON.stringify(filter)}.`);
  }
}
const selected = files.filter(
  (file) =>
    filters.length === 0 ||
    filters.some((filter) => `scripts/${file}`.includes(filter)),
);
const result = spawnSync(
  process.execPath,
  [
    "--test",
    "--test-concurrency=4",
    ...selected.map((name) => `scripts/${name}`),
  ],
  { cwd: frontendRoot, stdio: "inherit" },
);
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
