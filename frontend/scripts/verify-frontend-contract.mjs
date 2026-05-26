import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const srcDir = join(root, "src");
const forbiddenPathPatterns = [
  /public\/tmp/,
  /public\/mocks/,
  /\/tmp\//,
  /\/mocks\//,
  /\/api\/auth\/config/,
  /fetchAuthConfig/,
  /AuthConfig/,
  /ResumeMockPayload/,
];

async function collectFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const path = join(dir, entry.name);

    if (entry.isDirectory()) {
      files.push(...(await collectFiles(path)));
    } else if (/\.(ts|tsx|json)$/.test(entry.name)) {
      files.push(path);
    }
  }

  return files;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const files = await collectFiles(srcDir);
const resumeTypes = await readFile(join(srcDir, "types", "resume.ts"), "utf8");

assert(
  !/interface ModelConfig[\s\S]*apiKey:\s*string/.test(resumeTypes),
  "Persistent ModelConfig must not contain apiKey.",
);
assert(
  !/interface ModelConfig[\s\S]*apiKeyEnvName:\s*string/.test(resumeTypes),
  "Persistent ModelConfig must not contain apiKeyEnvName.",
);
assert(
  !/ResumeMockPayload/.test(resumeTypes),
  "Workspace payload types must not use mock naming.",
);

for (const file of files) {
  const content = await readFile(file, "utf8");

  for (const pattern of forbiddenPathPatterns) {
    assert(
      !pattern.test(content),
      `Forbidden static data path found in ${file}: ${pattern}`,
    );
  }
}

console.log(`Frontend contract verified across ${files.length} source files.`);
