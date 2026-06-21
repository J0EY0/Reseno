import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import vm from "node:vm";
import * as ts from "typescript";

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

async function loadTsModule(path) {
  const source = await readFile(path, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };

  vm.runInNewContext(compiled, {
    exports: module.exports,
    module,
  });

  return module.exports;
}

async function loadAgentToolDisplayHelpers() {
  return loadTsModule(join(srcDir, "lib", "agent-tool-display.ts"));
}

async function loadAgentMessageRenderingHelpers() {
  return loadTsModule(join(srcDir, "lib", "agent-message-rendering.ts"));
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

const { getVisibleCompletedTools } = await loadAgentToolDisplayHelpers();
const { isPlainAgentText } = await loadAgentMessageRenderingHelpers();
const tool = (id, title, state, purpose = "jd") => ({
  id,
  type: `tool-${title}`,
  title,
  state,
  input: { purpose },
});

assert(
  getVisibleCompletedTools([
    tool("search-1", "web_search", "output-available"),
    tool("fetch-error", "web_fetch", "output-error"),
    tool("search-2", "web_search", "output-available"),
    tool("fetch-1", "web_fetch", "output-available"),
    tool("search-error", "web_search", "output-error"),
    tool("search-3", "web_search", "output-available"),
    tool("fetch-2", "web_fetch", "output-available"),
  ])
    .map((item) => item.id)
    .join(",") === "search-3,fetch-2",
  "Recovered agent tool failures should be hidden from the visible timeline.",
);

assert(
  getVisibleCompletedTools([
    tool("search-error-1", "web_search", "output-error"),
    tool("search-error-2", "web_search", "output-error"),
  ])
    .map((item) => item.id)
    .join(",") === "search-error-2",
  "Unrecovered agent tool failures should be collapsed to the latest failure.",
);

assert(
  isPlainAgentText("根据招聘信息，这个岗位主要要求如下。"),
  "Plain agent text should stay eligible for inline citation rendering.",
);

assert(
  !isPlainAgentText("**核心职责**\n负责将 AI 能力落地到产品。"),
  "Markdown emphasis should render through MessageResponse, not plain text.",
);

assert(
  !isPlainAgentText("这里是 **重点** 内容。"),
  "Inline bold Markdown should render through MessageResponse.",
);

assert(
  !isPlainAgentText("使用 `React` 和 TypeScript。"),
  "Inline code Markdown should render through MessageResponse.",
);

assert(
  !isPlainAgentText("- 核心职责"),
  "Markdown lists should render through MessageResponse.",
);

assert(
  isPlainAgentText("熟悉 A* 搜索算法。"),
  "Plain text with a non-Markdown asterisk should keep inline citation rendering.",
);

console.log(`Frontend contract verified across ${files.length} source files.`);
