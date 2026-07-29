import { join } from "node:path";
import vm from "node:vm";
import { readFile } from "node:fs/promises";
import * as ts from "typescript";

const frontendRoot = new URL("..", import.meta.url).pathname;

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function loadTypeScriptModule(path) {
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
    require: () => ({}),
  });

  return module.exports;
}

const panelState = await loadTypeScriptModule(
  join(frontendRoot, "src", "lib", "agent-panel-state.ts"),
);
const panelSource = await readFile(
  join(
    frontendRoot,
    "src",
    "components",
    "copilot",
    "copilot-panel.tsx",
  ),
  "utf8",
);

const committedResponse = {
  edits: [{ id: "edit-1" }],
  transactionState: "committed",
};
const matchingDraft = {
  sourceMessageId: "assistant-2",
  status: "pending",
  transactionState: "committed",
};

assert(
  panelState
    .mergeStreamingAgentMessage(
      [{ id: "assistant-1", text: "persisted" }],
      { id: "assistant-2", text: "streaming" },
    )
    .map((message) => message.id)
    .join(",") === "assistant-1,assistant-2",
  "A new streaming message must appear after persisted history.",
);
const finalizedHandoff = panelState.mergeStreamingAgentMessage(
  [{ id: "assistant-1", text: "persisted final" }],
  { id: "assistant-1", text: "last streamed frame" },
);
assert(
  finalizedHandoff.length === 1 &&
    finalizedHandoff[0].text === "last streamed frame",
  "A final message and its last streamed frame must never render twice.",
);
assert(
  panelState.shouldShowAgentDraftActions({
    draft: matchingDraft,
    isResponding: false,
    messageId: "assistant-2",
    response: committedResponse,
  }),
  "A committed draft must be actionable on its source message.",
);
assert(
  !panelState.shouldShowAgentDraftActions({
    draft: matchingDraft,
    isResponding: false,
    messageId: "assistant-1",
    response: committedResponse,
  }),
  "A draft must never appear actionable on another assistant message.",
);
assert(
  panelState.shouldRollbackOptimisticAgentMessages({
    replaceSessionBeforeSend: false,
    runAccepted: false,
  }),
  "An unaccepted normal prompt must not remain as a ghost message.",
);
assert(
  panelState.shouldRollbackOptimisticAgentMessages({
    replaceSessionBeforeSend: true,
    runAccepted: false,
  }),
  "A failed history replacement must restore the prior local history.",
);
assert(
  !panelState.shouldRollbackOptimisticAgentMessages({
    replaceSessionBeforeSend: true,
    runAccepted: true,
  }),
  "Accepted runs own their persisted user message and must not be rolled back.",
);
assert(
  panelState.getAgentQualityWarningCount([
    {
      state: "output-available",
      output: { qualityIssueCount: 2 },
    },
    {
      state: "output-error",
      output: { qualityIssueCount: 9 },
    },
  ]) === 2,
  "Only completed tool outputs may contribute quality warnings.",
);
assert(
  panelSource.includes("shouldShowAgentDraftActions({"),
  "The Agent panel must bind draft actions to the draft source message.",
);
assert(
  !panelSource.includes("edits.slice(0, 4)"),
  "The confirmation panel must not silently hide edit operations.",
);
assert(
  panelSource.includes("activeUploadAbortRef.current.abort()"),
  "The stop action must cancel an in-flight attachment upload.",
);
assert(
  panelSource.includes("revision: sessionRevisionRef.current") ||
    panelSource.includes("revision,"),
  "Edited history replacement must carry the loaded session revision.",
);
assert(
  panelSource.includes('"AGENT_SESSION_REVISION_CONFLICT"'),
  "A stale history edit must reconcile with the authoritative session.",
);

console.log("Agent panel state checks passed.");

await import("./verify-agent-panel-races.mjs");
