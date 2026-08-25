import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const copilotRoot = path.join(
  frontendRoot,
  "src",
  "components",
  "copilot",
);
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

function countLines(source) {
  const lines = source.split(/\r\n|\n|\r/).length;
  return /(?:\r\n|\n|\r)$/.test(source) ? lines - 1 : lines;
}

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
  const limit = moduleName.endsWith(".tsx") ? 500 : 600;

  assert.ok(
    countLines(source) <= limit,
    `${moduleName} must stay within the default ${limit}-line source budget.`,
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

assert.match(panel, /export function CopilotPanel/);
assert.match(panel, /useAgentConversation\(/);
assert.match(panel, /useAgentPromptActions\(/);
assert.match(panel, /useAgentMessageActions\(/);
assert.match(panel, /<CopilotConversationView/);
assert.match(panel, /<CopilotComposer/);
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
assert.match(conversationView, /shouldShowAgentDraftActions\(/);
assert.match(conversationView, /<AgentAssistantMessageRow/);
assert.match(composer, /<CopilotModelSelector/);
assert.match(composer, /<AgentPromptSubmitButton/);

console.log("Agent controller/view module boundaries and budgets verified.");
