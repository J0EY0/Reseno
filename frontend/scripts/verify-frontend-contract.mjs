import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import ts from "typescript";
import { findNodes, parseSource } from "./source-analysis.mjs";

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
const apiTypes = await readFile(join(srcDir, "types", "api.ts"), "utf8");
const modelProviderIcon = await readFile(
  join(srcDir, "components", "model-provider-icon.tsx"),
  "utf8",
);
const modelProviders = await readFile(
  join(srcDir, "lib", "model-providers.ts"),
  "utf8",
);
const fontFamilyType = findNodes(
  parseSource(resumeTypes),
  ts.isTypeAliasDeclaration,
).find((node) => node.name.text === "ResumeFontFamily");
assert(
  fontFamilyType &&
    findNodes(fontFamilyType, ts.isStringLiteral).some(
      (node) => node.text === "noto_sans_sc",
    ),
  "The persisted Noto Sans SC value must belong to the font contract.",
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
  /import ZAI from "@lobehub\/icons\/es\/ZAI\/components\/Mono";/.test(
    modelProviderIcon,
  ),
  "Z.ai icon rendering must use the dedicated @lobehub/icons ZAI component.",
);
const providerIconImports = [
  ...modelProviderIcon.matchAll(/from "(@lobehub\/icons[^\"]+)"/g),
].map((match) => match[1]);
assert(
  providerIconImports.length > 0 &&
    providerIconImports.every((specifier) =>
      /^@lobehub\/icons\/es\/(Anthropic|DeepSeek|Google|Minimax|Moonshot|Ollama|OpenAI|Qwen|Vllm|XAI|ZAI)\/components\/(Mono|Color|Avatar)$/.test(
        specifier,
      ),
    ),
  "Provider icons must import only the finite set of displayed components, without package registries or text/combine variants.",
);
const agentChatRequestType =
  apiTypes.match(/export interface AgentChatRequest \{[\s\S]*?\n\}/)?.[0] ?? "";
const agentChatUserMessageType =
  apiTypes.match(/export interface AgentChatUserMessage \{[\s\S]*?\n\}/)?.[0] ??
  "";
assert(
  agentChatRequestType.length > 0 &&
    !/\bsettings\s*:/.test(agentChatRequestType),
  "The frontend Agent request contract must not expose persisted Agent preferences.",
);
assert(
  agentChatUserMessageType.length > 0 &&
    /\bid\s*:\s*string\s*;/.test(agentChatUserMessageType) &&
    /\brole\s*:\s*["']user["']\s*;/.test(agentChatUserMessageType) &&
    !/\bresponse\s*[?:]/.test(agentChatUserMessageType) &&
    /\bmessage\s*:\s*AgentChatUserMessage\s*;/.test(agentChatRequestType) &&
    /\bmessages\s*:\s*AgentConversationMessage\[\]\s*;/.test(
      agentChatRequestType,
    ) &&
    !/\b(?:prompt|files|conversation|clientTurnId)\s*[?:]/.test(
      agentChatRequestType,
    ),
  "AgentChatRequest must require canonical message/messages and expose no legacy turn fields.",
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
