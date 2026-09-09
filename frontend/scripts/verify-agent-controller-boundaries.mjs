import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const copilotRoot = path.join(frontendRoot, "src", "components", "copilot");
const modules = [
  "agent-conversation-runtime.ts",
  "copilot-composer.tsx",
  "copilot-conversation-view.tsx",
  "copilot-model-selector.tsx",
  "copilot-panel-types.ts",
  "copilot-panel.tsx",
  "use-agent-composer-layout.ts",
  "use-agent-conversation.ts",
  "use-agent-message-actions.ts",
  "use-agent-prompt-actions.ts",
  "use-agent-run-stream.ts",
  "use-agent-send-controller.ts",
  "use-agent-session-hydration.ts",
];

function resolveCopilotImport(moduleName, specifier) {
  if (!specifier.startsWith(".")) {
    return null;
  }

  const resolved = path.posix.normalize(
    path.posix.join(path.posix.dirname(moduleName), specifier),
  );
  for (const suffix of ["", ".ts", ".tsx"]) {
    const candidate = `${resolved}${suffix}`;
    if (modules.includes(candidate)) {
      return candidate;
    }
  }
  return null;
}

function collectDependencies(sourceFile, moduleName) {
  const dependencies = new Set();
  for (const statement of sourceFile.statements) {
    assert.equal(
      ts.isExportDeclaration(statement),
      false,
      `${moduleName} must not become a barrel or compatibility facade.`,
    );
    if (!ts.isImportDeclaration(statement)) {
      continue;
    }

    const dependency = resolveCopilotImport(
      moduleName,
      statement.moduleSpecifier.text,
    );
    if (dependency) {
      dependencies.add(dependency);
    }
  }
  return dependencies;
}

function assertAcyclic(graph) {
  const visiting = new Set();
  const visited = new Set();

  function visit(moduleName, trail) {
    if (visiting.has(moduleName)) {
      throw new Error(
        `Agent controller modules must remain acyclic: ${[
          ...trail,
          moduleName,
        ].join(" -> ")}`,
      );
    }
    if (visited.has(moduleName)) {
      return;
    }

    visiting.add(moduleName);
    for (const dependency of graph.get(moduleName) ?? []) {
      visit(dependency, [...trail, moduleName]);
    }
    visiting.delete(moduleName);
    visited.add(moduleName);
  }

  for (const moduleName of graph.keys()) {
    visit(moduleName, []);
  }
}

const graph = new Map();
const sources = new Map();

for (const moduleName of modules) {
  const source = await readFile(path.join(copilotRoot, moduleName), "utf8");
  const sourceFile = ts.createSourceFile(
    moduleName,
    source,
    ts.ScriptTarget.Latest,
    true,
    moduleName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  assert.doesNotMatch(
    source,
    /\b(?:createContext|useContext)\s*\(/,
    `${moduleName} must not replace explicit controller seams with a broad context.`,
  );
  graph.set(moduleName, collectDependencies(sourceFile, moduleName));
  sources.set(moduleName, source);
}

assertAcyclic(graph);

const panel = sources.get("copilot-panel.tsx");
const conversation = sources.get("use-agent-conversation.ts");
const sendController = sources.get("use-agent-send-controller.ts");
const promptActions = sources.get("use-agent-prompt-actions.ts");
const conversationView = sources.get("copilot-conversation-view.tsx");
const composer = sources.get("copilot-composer.tsx");
const modelSelector = sources.get("copilot-model-selector.tsx");

assert.match(panel, /export function CopilotPanel/);
assert.match(panel, /useAgentConversation\(/);
assert.match(panel, /useAgentPromptActions\(/);
assert.match(panel, /useAgentMessageActions\(/);
assert.match(panel, /<CopilotConversationView/);
assert.match(panel, /<CopilotComposer/);
assert.match(
  panel,
  /const agentModelConfigs = useMemo\([\s\S]{0,240}modelConfigs\.filter\(\(config\) => config\.supportsTools\)[\s\S]{0,100}\[modelConfigs\]/,
  "The Agent panel must derive its model options from tool-capable configs only.",
);
assert.match(
  panel,
  /agentModelConfigs\.find\(\(config\) => config\.id === selectedModelConfigId\) \?\?\s*null/,
  "An Agent selection without tool support must resolve to the unconfigured state.",
);
assert.doesNotMatch(
  panel,
  /modelConfigs\[0\]|agentModelConfigs\[0\]/,
  "The Agent must not silently fall back to a different model.",
);
assert.match(
  panel,
  /<CopilotComposer[\s\S]{0,500}modelConfigs=\{agentModelConfigs\}/,
  "The Agent model selector must receive only tool-capable configs.",
);
assert.doesNotMatch(
  panel,
  /@\/lib\/(?:agent-|api-client)|\b(?:toast|useState)\b/,
  "CopilotPanel must remain a narrow orchestration entry without transport or local state machines.",
);

assert.match(conversation, /useAgentRunStream\(/);
assert.match(conversation, /useAgentSendController\(/);
assert.match(conversation, /useAgentSessionHydration\(/);
assert.match(sendController, /shouldRollbackOptimisticAgentMessages\(/);
assert.match(sendController, /AGENT_SESSION_REVISION_CONFLICT/);
assert.match(sendController, /AGENT_REQUEST_DEBOUNCE_MS/);
assert.doesNotMatch(
  sendController,
  /\b(?:isLikelyJobBriefPrompt|onJobBriefChange|getKeywordMatch|jobBrief|keywordMatch)\b/,
  "Agent prompts must not mutate resume.jobBrief or client keyword scoring.",
);
assert.match(promptActions, /for \(const file of preparedFiles\)/);
assert.match(promptActions, /deletePendingUploads/);
assert.doesNotMatch(conversationView, /shouldShowAgentDraftActions\(/);
assert.match(conversationView, /<AgentAssistantMessageRow/);
assert.match(panel, /<AgentDraftReviewDock/);
assert.match(composer, /<CopilotModelSelector/);
assert.match(composer, /<AgentPromptSubmitButton/);
assert.match(
  sendController,
  /const modelConfigId = selectedModelConfig\?\.id \?\? null[\s\S]*modelConfig:\s*modelConfigId\s*\?\s*\{\s*id:\s*modelConfigId\s*\}\s*:\s*null/,
  "Agent requests must snapshot only the selected model config id before preparing.",
);
assert.match(
  composer,
  /const isRequestBusy = requestPhase !== ['"]idle['"]/,
  "Preparing and responding requests must share the next-message selection boundary.",
);
assert.match(
  composer,
  /<CopilotModelSelector\s*appliesToNextMessage=\{isRequestBusy\}\s*disabled=\{promptActions\.isSubmittingPrompt\}/,
  "Model selection must stay available after the current request snapshot is submitted.",
);
assert.match(
  composer,
  /const attachmentsReady\s*=\s*hasConfiguredModel\s*&&\s*isSessionReady\s*&&\s*!promptActions\.isSubmittingPrompt[\s\S]*<AgentPromptAttachmentButton\s*disabled=\{\s*!attachmentsReady\s*\|\|/,
  "Attachment staging must stay available after the current request snapshot is submitted.",
);
assert.match(
  modelSelector,
  /changed && appliesToNextMessage[\s\S]{0,120}toast\.info\(t\.agentModelChangedNextTurn/,
  "Changing models while a request is busy must explain that the new model applies to the next user turn.",
);
assert.match(
  modelSelector,
  /selectedModelConfig\s*\?\s*selectedModelConfigTriggerName\s*:\s*t\.agentModelNotConfigured/,
  "The selector trigger must visibly represent only the selected model.",
);
assert.doesNotMatch(
  modelSelector,
  /agentModelNextTurnShort|nextTurnPrefix/,
  "The selector trigger must not replace its model-selection label with next-turn status text.",
);

console.log("Agent controller/view module boundaries verified.");
