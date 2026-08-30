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
const apiTypes = await readFile(join(srcDir, "types", "api.ts"), "utf8");
const modelProviderIcon = await readFile(
  join(srcDir, "components", "model-provider-icon.tsx"),
  "utf8",
);
const modelProviders = await readFile(
  join(srcDir, "lib", "model-providers.ts"),
  "utf8",
);
const agentSendController = await readFile(
  join(
    srcDir,
    "components",
    "copilot",
    "use-agent-send-controller.ts",
  ),
  "utf8",
);
const agentPromptActions = await readFile(
  join(
    srcDir,
    "components",
    "copilot",
    "use-agent-prompt-actions.ts",
  ),
  "utf8",
);
const copilotAttachments = await readFile(
  join(srcDir, "components", "copilot", "copilot-attachments.tsx"),
  "utf8",
);
const copilotUserMessageRow = await readFile(
  join(srcDir, "components", "copilot", "copilot-user-message-row.tsx"),
  "utf8",
);
const promptInputForm = await readFile(
  join(srcDir, "components", "ai-elements", "use-prompt-input-form.ts"),
  "utf8",
);
const apiClient = await readFile(
  join(srcDir, "lib", "api-client.ts"),
  "utf8",
);
const agentAttachmentClient = await readFile(
  join(srcDir, "lib", "agent-attachment-client.ts"),
  "utf8",
);
const resumePreview = await readFile(
  join(srcDir, "components", "preview", "resume-preview.tsx"),
  "utf8",
);
const resumeFormatPopover = await readFile(
  join(srcDir, "components", "editor", "resume-format-popover.tsx"),
  "utf8",
);
const resumeDetailWorkspaceHeader = await readFile(
  join(
    srcDir,
    "components",
    "workspace",
    "resume-detail-workspace-header.tsx",
  ),
  "utf8",
);
const resumeDetailHeaderActions = await readFile(
  join(
    srcDir,
    "components",
    "workspace",
    "resume-detail-header-actions.tsx",
  ),
  "utf8",
);
const templateDetailWorkspaceHeader = await readFile(
  join(
    srcDir,
    "components",
    "workspace",
    "template-detail-workspace-header.tsx",
  ),
  "utf8",
);
const templateTypographyTab = await readFile(
  join(srcDir, "components", "templates", "editor", "typography-tab.tsx"),
  "utf8",
);
const templates = await readFile(join(srcDir, "lib", "templates.ts"), "utf8");
const zhMessages = JSON.parse(
  await readFile(join(srcDir, "i18n", "locales", "zh.json"), "utf8"),
);
const enMessages = JSON.parse(
  await readFile(join(srcDir, "i18n", "locales", "en.json"), "utf8"),
);

assert(
  /ResumeFontFamily\s*=\s*[^\n]*'noto_sans_sc'/.test(resumeTypes),
  "ResumeFontFamily must include the persisted Noto Sans SC value.",
);
assert(
  /noto_sans_sc:\s*"fontNotoSans"/.test(resumeFormatPopover) &&
    /supportedFontFamilies[\s\S]*?'noto_sans_sc'/.test(templates),
  "Resume and template normalization must preserve Noto Sans SC.",
);
assert(
  /<SelectItem value="noto_sans_sc">/.test(templateTypographyTab) &&
    zhMessages.fontNotoSans === "思源黑体" &&
    enMessages.fontNotoSans === "Noto Sans SC" &&
    zhMessages.fontSerif === "思源宋体" &&
    enMessages.fontSerif === "Noto Serif SC",
  "Both font selectors must expose the localized Noto Sans SC option.",
);
const resumeFormatSelectTriggers =
  resumeFormatPopover.match(/<SelectTrigger\b[^>]*>/g) ?? [];
const resumeFormatSelectContents =
  resumeFormatPopover.match(/<SelectContent\b[^>]*>/g) ?? [];
const hasStaticClass = (tag, className) =>
  (tag.match(/\bclassName="([^"]*)"/)?.[1].split(/\s+/) ?? []).includes(
    className,
  );
const getStaticClasses = (tag) =>
  tag.match(/\bclassName="([^"]*)"/)?.[1].split(/\s+/) ?? [];
const getResumeFormatTrigger = (label) =>
  resumeFormatSelectTriggers.find((tag) =>
    tag.includes(`aria-label={t.${label}}`),
  );
const hasExactBaseWidth = (tag, width) => {
  const widths = getStaticClasses(tag).filter((name) =>
    /^w-(?:\d+|\[)/.test(name),
  );

  return widths.length === 1 && widths[0] === width;
};
const exportMenuTriggerButton =
  resumeDetailHeaderActions.match(
    /<DropdownMenuTrigger asChild>\s*(<Button\b[^>]*>)/,
  )?.[1] ?? "";
const exportMenuContent =
  resumeDetailHeaderActions.match(/<DropdownMenuContent\b[^>]*>/)?.[0] ?? "";
const resumeBackButton =
  resumeDetailWorkspaceHeader.match(
    /<Button\b(?=[^>]*onClick=\{commands\.back\})[^>]*>/,
  )?.[0] ?? "";
const templateBackButton =
  templateDetailWorkspaceHeader.match(
    /<Button\b(?=[^>]*onClick=\{onBack\})[^>]*>/,
  )?.[0] ?? "";

assert(
  [resumeBackButton, templateBackButton].every(
    (tag) => tag.includes('variant="outline"') && !/\bsize=/.test(tag),
  ),
  "Detail-header back actions must remain outline buttons at the shared default toolbar size.",
);

assert(
  hasStaticClass(exportMenuTriggerButton, "min-w-32") &&
    hasStaticClass(
      exportMenuContent,
      "w-[var(--radix-dropdown-menu-trigger-width)]",
    ) &&
    hasStaticClass(
      exportMenuContent,
      "min-w-[var(--radix-dropdown-menu-trigger-width)]",
    ),
  "Resume export menu must exactly match its trigger width.",
);

assert(
  resumeFormatSelectTriggers.length === 3 &&
    [
      ["applyTemplate", "w-32"],
      ["fontFamily", "w-36"],
      ["fontSize", "w-24"],
    ].every(([label, width]) => {
      const trigger = getResumeFormatTrigger(label);

      return (
        trigger?.includes('size="sm"') && hasExactBaseWidth(trigger, width)
      );
    }) &&
    hasStaticClass(
      getResumeFormatTrigger("fontFamily") ?? "",
      "[&:lang(zh)]:w-28",
    ),
  "Resume format select triggers must use content-sized compact widths.",
);
assert(
  resumeFormatSelectContents.length === 3 &&
    resumeFormatSelectContents.every(
      (tag) =>
        tag.includes('align="end"') &&
        tag.includes('position="popper"') &&
        !tag.includes("--radix-select-trigger-width"),
    ) &&
    !resumeFormatPopover.includes("sideOffset="),
  "Resume format select poppers must use shared width and standard spacing.",
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
  /import ZAI from "@lobehub\/icons\/es\/ZAI";/.test(
    modelProviderIcon,
  ),
  "Z.ai icon rendering must use the dedicated @lobehub/icons ZAI entrypoint.",
);
const providerAliases =
  modelProviderIcon.match(/const PROVIDER_ALIASES[^=]*=\s*\{([\s\S]*?)\n};/)?.[1] ?? "";
const providerIcons =
  modelProviderIcon.match(/const PROVIDER_ICONS\s*=\s*\{([\s\S]*?)\n} as const;/)?.[1] ?? "";
assert(
  /\bglm:\s*"zai"/.test(providerAliases) &&
    /\bzhipu:\s*"zai"/.test(providerAliases) &&
    /\bzhipuai:\s*"zai"/.test(providerAliases) &&
    /\bzai:\s*ZAI\b/.test(providerIcons),
  "Z.ai provider ids must normalize to the dedicated ZAI icon mapping.",
);
assert(
  /const normalizedProvider = PROVIDER_ALIASES\[provider\] \?\? provider;[\s\S]*?if \(!hasProviderIcon\(normalizedProvider\)\)[\s\S]*?const ProviderIcon = PROVIDER_ICONS\[normalizedProvider\];/.test(
    modelProviderIcon,
  ),
  "Provider aliases must be resolved before the generic icon fallback.",
);
assert(
  !/glm:\s*"zhipu"|zhipuai:\s*"zhipu"/.test(modelProviderIcon),
  "Z.ai provider ids must not alias to the legacy Zhipu ProviderIcon.",
);
assert(
  !/continuing with chat request/.test(agentSendController),
  "Editing must stop when persisted Agent history replacement fails.",
);
assert(
  !/settings:\s*agentSettings/.test(agentSendController),
  "Agent chat requests must not resend backend-owned Agent preferences.",
);
const agentChatRequestType =
  apiTypes.match(/export interface AgentChatRequest \{[\s\S]*?\n\}/)?.[0] ?? "";
const agentChatUserMessageType =
  apiTypes.match(/export interface AgentChatUserMessage \{[\s\S]*?\n\}/)?.[0] ?? "";
assert(
  agentChatRequestType.length > 0 && !/\bsettings\s*:/.test(agentChatRequestType),
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
const agentChatPostPayload =
  agentSendController.match(
    /sendAgentChatMessage\(\s*(\{[\s\S]*?\})\s*,\s*\{\s*\.\.\.streamOptions,/,
  )?.[1] ?? "";
const currentAgentChatMessageBuilder =
  agentSendController.match(
    /const currentMessage:\s*AgentChatUserMessage\s*=\s*\{([\s\S]*?)\n\s*\}/,
  )?.[1] ?? "";
assert(
  currentAgentChatMessageBuilder.length > 0 &&
    /\bid:\s*userMessage\.id\s*,/.test(currentAgentChatMessageBuilder) &&
    /\brole:\s*["']user["']\s*,/.test(currentAgentChatMessageBuilder) &&
    /\btext:\s*prompt\s*,/.test(currentAgentChatMessageBuilder) &&
    /\bfiles\s*,/.test(currentAgentChatMessageBuilder) &&
    !/\bresponse\s*:/.test(currentAgentChatMessageBuilder) &&
    !/toConversationMessage\(userMessage\)/.test(agentSendController),
  "The current Agent turn builder must produce only the canonical user-message fields.",
);
assert(
  agentChatPostPayload.length > 0 &&
    /^\s*message\s*:/m.test(agentChatPostPayload) &&
    /^\s*messages\s*:/m.test(agentChatPostPayload) &&
    !/^\s*(?:prompt|files|conversation|clientTurnId)\s*:/m.test(
      agentChatPostPayload,
    ),
  "Agent chat POSTs must send only the canonical current message and prior messages fields.",
);
assert(
  /const\s+priorMessages\s*=\s*baseMessages\.map\(toConversationMessage\)/.test(
    agentSendController,
  ) &&
    /const\s+apiMessages\s*=\s*\[\.\.\.priorMessages,\s*currentMessage\]/.test(
      agentSendController,
    ) &&
    /^\s*message\s*:\s*currentMessage\s*,/m.test(agentChatPostPayload) &&
    /^\s*messages\s*:\s*resumeId\s*\?\s*\[\]\s*:\s*priorMessages\s*,/m.test(
      agentChatPostPayload,
    ) &&
    /replaceAgentSession\([\s\S]{0,300}messages:\s*apiMessages/.test(
      agentSendController,
    ),
  "Persisted chat POSTs must omit client history, temporary chats must retain it, and session replacement must include the full edited history.",
);
assert(
  /if\s*\(\s*\(!prompt\s*&&\s*files\.length\s*===\s*0\)\s*\|\|\s*runtime\.isResponding/.test(
    agentSendController,
  ) &&
    /const\s+userMessage:[\s\S]{0,240}\bfiles,?[\s\S]{0,240}\btext:\s*prompt/.test(
      agentSendController,
    ) &&
    /^\s*message\s*:\s*currentMessage\s*,/m.test(agentChatPostPayload),
  "File-only Agent turns must remain valid and carry their attachments in the current message.",
);
assert(
  /status\s*!==\s*['"]completed['"][\s\S]{0,900}shouldRollbackOptimisticAgentMessages\([\s\S]{0,500}updates\.setMessages\(pending\.rollbackMessages\)/.test(
    agentSendController,
  ),
  "Every non-completed Agent request must apply the optimistic-message rollback policy.",
);
assert(
  /function AgentUserMessageRow[\s\S]{0,3000}message\.files\?\.length[\s\S]{0,500}<AgentMessageAttachments[\s\S]{0,500}files=\{message\.files\}/.test(
    copilotUserMessageRow,
  ),
  "User message rendering must consume message.files through the attachment renderer.",
);

const uploadStateDeclaration = agentPromptActions.match(
  /const\s*\[\s*(is\w*(?:Uploading|Submitting)\w*)\s*,\s*(set\w*(?:Uploading|Submitting)\w*)\s*\]\s*=\s*useState(?:<boolean>)?\(false\)/,
);
assert(
  uploadStateDeclaration,
  "Agent attachment uploads must expose reactive uploading/submitting state.",
);

const uploadStateName =
  uploadStateDeclaration?.[1] ?? "__missingUploadState";
const uploadStateSetter =
  uploadStateDeclaration?.[2] ?? "__missingUploadStateSetter";
const submitPromptStart = agentPromptActions.indexOf(
  "const submitPrompt = useCallback(",
);
const submitPromptEnd = agentPromptActions.indexOf(
  "const stopResponding",
  submitPromptStart,
);
const submitPromptSource =
  submitPromptStart >= 0 && submitPromptEnd > submitPromptStart
    ? agentPromptActions.slice(submitPromptStart, submitPromptEnd)
    : "";

assert(
  new RegExp(
    `if\\s*\\([\\s\\S]{0,160}\\b${uploadStateName}\\b`,
  ).test(submitPromptSource) &&
    new RegExp(
      `\\b${uploadStateSetter}\\(true\\)[\\s\\S]*\\b${uploadStateSetter}\\(false\\)`,
    ).test(submitPromptSource),
  "Prompt submission must reject re-entry and keep reactive state active for the full attachment upload.",
);
const sendControlUsesUploadState =
  new RegExp(
    `<PromptInputSubmit[\\s\\S]{0,1800}disabled=\\{[\\s\\S]{0,180}\\b${uploadStateName}\\b`,
  ).test(agentPromptActions) ||
  new RegExp(
    `function AgentPromptSubmitButton[\\s\\S]{0,1800}const isDisabled\\s*=[\\s\\S]{0,300}\\b${uploadStateName}\\b[\\s\\S]{0,1800}disabled=\\{isDisabled\\}`,
  ).test(copilotAttachments);

assert(
  sendControlUsesUploadState,
  "The Agent send control must be disabled while attachments are uploading.",
);
assert(
  /onUploadProgress:[\s\S]{0,180}options\.onProgress/.test(apiClient) &&
    /uploadAgentAttachment\([\s\S]{0,240}onProgress[\s\S]{0,180}uploadApi<AgentChatAttachment>/.test(
      agentAttachmentClient,
    ),
  "Agent attachment uploads must forward real transport progress from the API client.",
);
assert(
  /uploadAgentAttachment\([\s\S]*?\(\{\s*loaded,\s*total\s*\}\)\s*=>[\s\S]*?setAttachmentUploadProgress/.test(
    submitPromptSource,
  ) &&
    /setAttachmentUploadProgress\(\s*Math\.min\(\s*99,/.test(
      submitPromptSource,
    ) &&
    /<PromptInputSubmit[\s\S]{0,1800}\{attachmentUploadProgress\}%/.test(
      copilotAttachments,
    ),
  "The Agent send control must render aggregate attachment upload progress.",
);
assert(
  /const\s+sendOperation\s*=\s*sendPrompt\(/.test(submitPromptSource) &&
    /requestAccepted\s*=\s*await\s+sendOperation\.accepted/.test(
      submitPromptSource,
    ) &&
    /if\s*\(!requestAccepted\)\s*\{[\s\S]{0,180}await\s+sendOperation\.completion[\s\S]{0,180}throw/.test(
      submitPromptSource,
    ) &&
    /void\s+sendOperation\.completion/.test(submitPromptSource),
  "The composer must clear after the uploaded prompt is accepted, not after the full Agent run completes.",
);
assert(
  /const convertedFiles = await Promise\.all\([\s\S]*?if \(!mountedRef\.current\) \{\s*return;\s*\}[\s\S]*?const result = onSubmit\(/.test(
    promptInputForm,
  ) &&
    /if \(result instanceof Promise\) \{\s*await result;\s*\}\s*for \(const \{ id \} of activeFiles\)[\s\S]{0,80}remove\(id\)/.test(
    promptInputForm,
  ) &&
    !/await result;\s*\}\s*if \(!mountedRef\.current\)/.test(
      promptInputForm,
    ) &&
    /shouldClearPromptSubmissionText\([\s\S]{0,100}latestController\.textInput\.value[\s\S]{0,100}latestController\.textInput\.clear\(\)/.test(
      promptInputForm,
    ) &&
    /catch \{\s*\/\/ Keep the captured input and attachments available for retry\./.test(
      promptInputForm,
    ),
  "Unmounting may block a stale request, but an accepted submission must still clear only its captured attachments and unchanged text.",
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
const tool = (id, title, state, url = "https://example.com/job") => ({
  id,
  type: `tool-${title}`,
  title,
  state,
  input: { url },
});

assert(
  getVisibleCompletedTools([
    tool("fetch-1", "web_fetch", "output-available"),
    tool("fetch-error-1", "web_fetch", "output-error"),
    tool("fetch-2", "web_fetch", "output-available"),
    tool("fetch-3", "web_fetch", "output-available"),
    tool("fetch-error-2", "web_fetch", "output-error"),
    tool("fetch-4", "web_fetch", "output-available"),
    tool("fetch-5", "web_fetch", "output-available"),
  ])
    .map((item) => item.id)
    .join(",") === "fetch-1,fetch-2,fetch-3,fetch-4,fetch-5",
  "Recovered failures should be hidden while every successful invocation remains auditable.",
);

assert(
  getVisibleCompletedTools([
    tool("fetch-error-1", "web_fetch", "output-error"),
    tool("fetch-error-2", "web_fetch", "output-error"),
  ])
    .map((item) => item.id)
    .join(",") === "fetch-error-2",
  "Unrecovered agent tool failures should be collapsed to the latest failure.",
);

assert(
  isPlainAgentText("根据招聘信息，这个岗位主要要求如下。"),
  "Plain agent text should stay eligible for lightweight rendering.",
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
  "Plain text with a non-Markdown asterisk should keep lightweight rendering.",
);

console.log(`Frontend contract verified across ${files.length} source files.`);
