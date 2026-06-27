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
const modelConfigForm = await readFile(
  join(srcDir, "components", "model-config-form-popover.tsx"),
  "utf8",
);
const modelProviderIcon = await readFile(
  join(srcDir, "components", "model-provider-icon.tsx"),
  "utf8",
);
const modelProviders = await readFile(
  join(srcDir, "lib", "model-providers.ts"),
  "utf8",
);

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
assert(
  /interface ModelConfig[\s\S]*providerLabel:\s*string[\s\S]*iconProvider:\s*string/.test(
    resumeTypes,
  ),
  "ModelConfig responses must carry backend provider display metadata.",
);
assert(
  /interface ModelConfig[\s\S]*supportsTools:\s*boolean[\s\S]*supportsStreaming:\s*boolean/.test(
    resumeTypes,
  ),
  "ModelConfig responses must carry agent-critical capability metadata.",
);
assert(
  !/export const MODEL_PROVIDERS|defaultBaseUrl:\s*["']|officialUrl:\s*["']|authRequired:\s*(true|false)/.test(
    modelProviders,
  ),
  "Frontend must not maintain provider manifest entries; use the backend manifest.",
);
assert(
  !/PROVIDER_ALIASES|normalizeProviderId|inferModelProviderId|DEFAULT_MODEL_PROVIDER_ID/.test(
    modelProviders,
  ),
  "Frontend must not normalize or infer provider ids; provider ids come from the backend manifest.",
);
assert(
  /interface ModelProviderMeta[\s\S]*supportsTools:\s*boolean[\s\S]*supportsStreaming:\s*boolean/.test(
    modelProviders,
  ),
  "Provider manifest metadata must expose agent-critical capabilities.",
);

assert(
  /usesDiscoveredModelSelect\s*=[\s\S]*draft\.providerKind === "cloud"[\s\S]*?<Select[\s\S]*?onValueChange=\{handleModelSelect\}/.test(
    modelConfigForm,
  ),
  "Cloud provider configs must use discovered model selection, not manual model input.",
);
assert(
  /function providerDisplayLabel[\s\S]*custom-cloud[\s\S]*t\.customCloudApi/.test(
    modelConfigForm,
  ),
  "Custom Cloud API provider label must be localized.",
);
assert(
  /function providerKindLabel[\s\S]*localProvider[\s\S]*cloudProvider/.test(
    modelConfigForm,
  ),
  "Provider options must show local or cloud tags consistently.",
);
assert(
  /PROVIDER_KIND_TAG_CLASS_NAME\s*=\s*[\s\S]*rounded-full[\s\S]*border-border\/60/.test(
    modelConfigForm,
  ),
  "Provider kind tags must use the bordered pill style in both trigger and options.",
);
assert(
  /\{draft\.providerKind !== "cloud" \? \([\s\S]*?name="model-api-url"[\s\S]*?\) : null\}/.test(
    modelConfigForm,
  ),
  "Cloud provider configs must not expose a manual API URL input.",
);
assert(
  /modelDiscoveryApiUrl\s*=\s*draft\.providerKind === "cloud" \? cloudApiUrl : draft\.apiUrl\.trim\(\)/.test(
    modelConfigForm,
  ),
  "Model discovery must use the provider manifest API URL for cloud providers and the typed API URL for local providers.",
);
assert(
  /discoverModels\(\{[\s\S]*apiUrl:\s*modelDiscoveryApiUrl/.test(modelConfigForm),
  "Model discovery requests must use the resolved discovery API URL.",
);
assert(
  /refresh:\s*true/.test(modelConfigForm),
  "Provider requests must only refresh models after an explicit user action.",
);
assert(
  /nextModels\.length === 1 \? nextModels\[0\] : null/.test(
    modelConfigForm,
  ),
  "Model discovery must only auto-select when exactly one model is available.",
);
assert(
  /onValueChange=\{handleModelSelect\}[\s\S]*?<SelectTrigger className="[^"]*\bw-full\b[\s\S]*?<SelectValue[\s\S]*?<SelectContent[\s\S]*?position="popper"/.test(
    modelConfigForm,
  ),
  "Discovered model selection must render a full-width popper dropdown.",
);
assert(
  /apiUrl:\s*providerKind === "cloud"\s*\?\s*cloudApiUrl\s*:\s*draft\.apiUrl\.trim\(\)/.test(
    modelConfigForm,
  ),
  "Saved cloud model configs must use the provider manifest API URL.",
);
assert(
  /usesManualModelSettings\s*=[\s\S]*Boolean\(selectedProvider\)[\s\S]*!usesDiscoveredModelSelect/.test(
    modelConfigForm,
  ),
  "Manual provider form state must cover local and custom providers.",
);
assert(
  /usesManualModelSettings \? \([\s\S]*?t\.capabilities[\s\S]*?t\.visionCapability[\s\S]*?t\.reasoningCapability[\s\S]*?t\.toolUseCapability[\s\S]*?t\.advancedSettings[\s\S]*?name="model-context-window"[\s\S]*?name="model-max-tokens"[\s\S]*?\) : null/.test(
    modelConfigForm,
  ),
  "Manual model configs must expose capabilities, context window, and max output tokens.",
);
assert(
  !/name="model-temperature"|name="model-top-p"/.test(modelConfigForm),
  "Manual model config UI must not expose temperature or topP.",
);
assert(
  /temperature:\s*null[\s\S]*topP:\s*null/.test(
    modelConfigForm,
  ),
  "Model config form must not submit temperature and topP.",
);
assert(
  /supportsImage:\s*draft\.supportsImage[\s\S]*supportsThinking/.test(
    modelConfigForm,
  ),
  "Manual model configs must submit configured capabilities.",
);
assert(
  /checked=\{draft\.supportsTools\}[\s\S]*updateField\("supportsTools",\s*event\.target\.checked\)[\s\S]*t\.toolUseCapability/.test(
    modelConfigForm,
  ),
  "Manual model configs must let users declare tool support.",
);
assert(
  /ZAI_PROVIDER_IDS\s*=\s*new Set\(\[[\s\S]*"glm"[\s\S]*"zai"[\s\S]*"zhipu"[\s\S]*"zhipuai"[\s\S]*\]\)/.test(
    modelProviderIcon,
  ),
  "Z.ai provider ids must be handled by the dedicated ZAI icon mapping.",
);
assert(
  /module\.ZAI\s+as\s+LobeCompoundIcon/.test(modelProviderIcon),
  "Z.ai icon rendering must use @lobehub/icons ZAI.",
);
assert(
  /ZAI_PROVIDER_IDS\.has\(provider\)[\s\S]*LoadedZaiIcon/.test(
    modelProviderIcon,
  ),
  "Z.ai providers must render the loaded ZAI icon before the ProviderIcon fallback.",
);
assert(
  !/glm:\s*"zhipu"|zhipuai:\s*"zhipu"/.test(modelProviderIcon),
  "Z.ai provider ids must not alias to the legacy Zhipu ProviderIcon.",
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
