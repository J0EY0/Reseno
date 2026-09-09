import { join } from "node:path";
import { readFile } from "node:fs/promises";
import ts from "typescript";
import { findNodes, getMemberPath, parseSource } from "./source-analysis.mjs";

import { evaluateTypeScript } from "./typescript-module.mjs";

const frontendRoot = new URL("..", import.meta.url).pathname;

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function loadTypeScriptModule(path) {
  const source = await readFile(path, "utf8");

  return evaluateTypeScript(source);
}

const panelState = await loadTypeScriptModule(
  join(frontendRoot, "src", "lib", "agent-panel-state.ts"),
);
const copilotRoot = join(frontendRoot, "src", "components", "copilot");
const [panelSource, conversationViewSource, promptActionsSource, sendSource] =
  await Promise.all([
    readFile(join(copilotRoot, "copilot-panel.tsx"), "utf8"),
    readFile(join(copilotRoot, "copilot-conversation-view.tsx"), "utf8"),
    readFile(join(copilotRoot, "use-agent-prompt-actions.ts"), "utf8"),
    readFile(join(copilotRoot, "use-agent-send-controller.ts"), "utf8"),
  ]);

assert(
  panelState
    .mergeStreamingAgentMessage([{ id: "assistant-1", text: "persisted" }], {
      id: "assistant-2",
      text: "streaming",
    })
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
const qualityWarnings = panelState.getAgentQualityWarnings([
  {
    state: "output-available",
    output: {
      qualityIssues: [
        {
          code: "target_requirements_not_covered",
          severity: "warning",
          target: "resume",
        },
        {
          code: "unsupported_edit_claim",
          severity: "warning",
          target: "basic.summary",
        },
      ],
    },
  },
  {
    state: "output-error",
    output: {
      qualityIssues: [
        {
          code: "must-not-surface",
          severity: "warning",
          target: "resume",
        },
      ],
    },
  },
]);
assert(
  qualityWarnings.map((issue) => issue.code).join(",") ===
    "target_requirements_not_covered,unsupported_edit_claim",
  "Only advisory issues from completed tool outputs may be shown.",
);
assert(
  panelState.getAgentQualityWarnings([
    {
      state: "output-available",
      output: {
        qualityIssues: [
          {
            code: "mixed_resume_languages",
            severity: "warning",
            target: "resume",
          },
          {
            code: "mixed_resume_languages",
            severity: "warning",
            target: "resume",
          },
        ],
      },
    },
  ]).length === 1,
  "Repeated quality diagnostics must render only once.",
);
assert(
  panelState.canSubmitAgentPrompt({
    hasConfiguredModel: true,
    isRequestBusy: false,
    isSessionReady: true,
    isSubmitting: false,
  }),
  "A ready idle Agent with a configured model may submit.",
);
assert(
  !panelState.canSubmitAgentPrompt({
    hasConfiguredModel: true,
    isRequestBusy: false,
    isSessionReady: false,
    isSubmitting: false,
  }),
  "A failed or pending bootstrap must keep the composer send gate closed.",
);
assert(
  !panelState.canSubmitAgentPrompt({
    hasConfiguredModel: true,
    isRequestBusy: true,
    isSessionReady: true,
    isSubmitting: false,
  }),
  "Preparing and responding phases must both keep the composer send gate closed.",
);
assert(
  panelSource.includes("<AgentDraftReviewDock") &&
    !conversationViewSource.includes("shouldShowAgentDraftActions"),
  "Pending draft decisions must live in the measured composer dock instead of message history.",
);
assert(
  !`${panelSource}\n${conversationViewSource}`.includes("edits.slice(0, 4)"),
  "The confirmation panel must not silently hide edit operations.",
);
assert(
  promptActionsSource.includes("activeUploadAbortRef.current.abort()"),
  "The stop action must cancel an in-flight attachment upload.",
);
const stopDeclaration = findNodes(
  parseSource(promptActionsSource),
  ts.isVariableDeclaration,
).find((node) => getMemberPath(node.name) === "stopResponding");
const stopCallback = stopDeclaration?.initializer?.arguments?.[0];
assert(stopCallback, "The composer must expose its stop action.");
for (const [isSubmittingPrompt, ownsUpload, expected] of [
  [true, true, "upload"],
  [false, true, "conversation"],
  [true, false, "conversation"],
]) {
  const events = [];
  const { stop } = evaluateTypeScript(
    `export const stop = ${stopCallback.getText()};`,
    {
      globals: {
        isSubmittingPrompt,
        activeUploadAbortRef: {
          current: ownsUpload ? { abort: () => events.push("upload") } : null,
        },
        stopConversation: () => events.push("conversation"),
      },
    },
  );
  stop();
  assert(
    JSON.stringify(events) === JSON.stringify([expected]),
    "Stop must cancel the current upload or the accepted conversation exactly once.",
  );
}

assert(
  sendSource.includes("revision,"),
  "Edited history replacement must carry the loaded session revision.",
);
assert(
  findNodes(parseSource(sendSource), ts.isStringLiteral).some(
    (node) => node.text === "AGENT_SESSION_REVISION_CONFLICT",
  ),
  "A stale history edit must reconcile with the authoritative session.",
);

console.log("Agent panel state checks passed.");
