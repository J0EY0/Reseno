import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const sourceRoot = new URL("../src/", import.meta.url);
const [
  packageManifest,
  messagePrimitives,
  messageResponse,
  responseContent,
  presentation,
  assistantResponse,
  toolPresentation,
  changeSummary,
  userMessageRow,
  promptInput,
  shimmer,
] = await Promise.all([
  readFile(new URL("../package.json", import.meta.url), "utf8"),
  readFile(new URL("components/ai-elements/message.tsx", sourceRoot), "utf8"),
  readFile(
    new URL("components/ai-elements/message-response.tsx", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/copilot/copilot-response-content.tsx", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/copilot/copilot-message-presentation.tsx", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/copilot/copilot-assistant-response.tsx", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/copilot/copilot-tool-presentation.tsx", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/copilot/copilot-change-summary.tsx", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/copilot/copilot-user-message-row.tsx", sourceRoot),
    "utf8",
  ),
  readFile(new URL("components/ai-elements/prompt-input.tsx", sourceRoot), "utf8"),
  readFile(new URL("components/ai-elements/shimmer.tsx", sourceRoot), "utf8"),
]);

assert(
  !messagePrimitives.includes("streamdown") &&
    !messagePrimitives.includes("@streamdown/"),
  "Lightweight message primitives must not pull rich rendering into the Agent shell.",
);
assert(
  messageResponse.includes('from "streamdown"') &&
    messageResponse.includes('from "@streamdown/math"') &&
    messageResponse.includes('from "@streamdown/mermaid"'),
  "The optional response module must retain the existing rich rendering plugins.",
);
assert(
  /lazy\(\(\)\s*=>[\s\S]*?import\("@\/components\/ai-elements\/message-response"\)/.test(
    responseContent,
  ),
  "Rich Agent responses must use a statically analyzable dynamic import.",
);
assert(
  /isPlainAgentText\(responseText\)[\s\S]{0,180}AgentPlainResponse/.test(
    assistantResponse,
  ) &&
    /AgentRichResponse text=\{responseText\}/.test(assistantResponse),
  "Plain responses must stay lightweight while Markdown uses the optional renderer.",
);
assert(
  /memo\(function AgentAssistantMessageRow/.test(presentation) &&
    presentation.includes("AgentMessageTimeline") &&
    presentation.includes("AgentChangeSummary") &&
    !presentation.includes("InlineCitation") &&
    !presentation.includes("Collapsible"),
  "The memoized assistant row must remain a small streaming orchestration seam.",
);
assert(
  /export function AgentMessageTimeline/.test(toolPresentation) &&
    /export function AgentAssistantActivity/.test(toolPresentation) &&
    toolPresentation.includes("getVisibleCompletedTools"),
  "Timeline ordering and tool lifecycle presentation must stay in one deep module.",
);
assert(
  /export function AgentChangeSummary/.test(changeSummary) &&
    changeSummary.includes("isAgentEditExecutionTool") &&
    changeSummary.includes("getAgentQualityWarningCount"),
  "Change-summary decoding and quality warnings must stay behind the summary seam.",
);
assert(
  /export function AgentUserMessageRow/.test(userMessageRow) &&
    userMessageRow.includes("<AgentMessageAttachments") &&
    userMessageRow.includes("message.execution?.status"),
  "User message attachments, editing, and retry state must stay owned by the row.",
);
assert(
  !shimmer.includes('from "motion/react"') &&
    !JSON.parse(packageManifest).dependencies.motion,
  "The single text shimmer must use its CSS animation without a motion runtime.",
);
assert(
  !/components\/ui\/(?:command|dropdown-menu|hover-card|select)/.test(
    promptInput,
  ) &&
    promptInput.includes("usePromptInputForm"),
  "PromptInput must retain only its used form primitives behind the deep form hook.",
);

console.log("Agent rendering bundle boundaries verified.");
