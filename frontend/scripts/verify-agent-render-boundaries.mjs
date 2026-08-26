import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const sourceRoot = new URL("../src/", import.meta.url);
const [
  packageManifest,
  messagePrimitives,
  messageResponse,
  inlineCitation,
  responseContent,
  presentation,
  assistantResponse,
  toolPresentation,
  changeSummary,
  conversationView,
  userMessageRow,
  promptInput,
  shimmer,
  appStyles,
] = await Promise.all([
  readFile(new URL("../package.json", import.meta.url), "utf8"),
  readFile(new URL("components/ai-elements/message.tsx", sourceRoot), "utf8"),
  readFile(
    new URL("components/ai-elements/message-response.tsx", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/ai-elements/inline-citation.tsx", sourceRoot),
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
    new URL("components/copilot/copilot-conversation-view.tsx", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/copilot/copilot-user-message-row.tsx", sourceRoot),
    "utf8",
  ),
  readFile(new URL("components/ai-elements/prompt-input.tsx", sourceRoot), "utf8"),
  readFile(new URL("components/ai-elements/shimmer.tsx", sourceRoot), "utf8"),
  readFile(new URL("index.css", sourceRoot), "utf8"),
]);

const agentThreadScrollRule = appStyles.match(
  /\.agent-thread-scroll\s*\{(?<body>[\s\S]*?)\n\}/,
);

assert(agentThreadScrollRule, "The Agent thread scroll style must exist.");
assert.doesNotMatch(
  agentThreadScrollRule.groups.body,
  /(?:-webkit-)?mask(?:-image)?\s*:/,
  "The native Agent scroll owner must never be masked because the browser applies that mask to its scrollbar too.",
);

assert(
  !messagePrimitives.includes("streamdown") &&
    !messagePrimitives.includes("@streamdown/"),
  "Lightweight message primitives must not pull rich rendering into the Agent shell.",
);
assert(
  /messages\.findLast\(\s*\(candidate\) => candidate\.role === 'user',?\s*\)\?\.id/.test(
    conversationView,
  ) &&
    /retryable=\{message\.id === latestUserMessageId\}/.test(conversationView) &&
    !/retryable=\{message\.id === messages\.at\(-1\)\?\.id\}/.test(
      conversationView,
    ),
  "Retry must follow the latest user turn even when a cancelled run persists a partial assistant message after it.",
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
  /isPlainAgentText\(text\)[\s\S]{0,180}AgentPlainResponse/.test(
    assistantResponse,
  ) &&
    /AgentRichResponse[\s\S]{0,120}text=\{text\}/.test(
      assistantResponse,
    ),
  "Plain responses must stay lightweight while Markdown uses the optional renderer.",
);
assert(
  assistantResponse.includes(
    'from "@/components/ai-elements/inline-citation"',
  ) &&
    assistantResponse.includes("<InlineCitation>") &&
    assistantResponse.includes("<InlineCitationCard>") &&
    assistantResponse.includes("<InlineCitationCardTrigger") &&
    assistantResponse.includes("<InlineCitationCardBody>") &&
    assistantResponse.includes("<InlineCitationCarousel>") &&
    assistantResponse.includes("<InlineCitationSource") &&
    assistantResponse.includes("sourceByUrl") &&
    !assistantResponse.includes("<citation") &&
    !assistantResponse.includes('from "@/components/ai-elements/sources"') &&
    !assistantResponse.includes("source.excerpt") &&
    responseContent.includes("inlineTail") &&
    responseContent.includes("[&>p:last-child]:inline"),
  "Agent sources must use one official hover citation attached to the response tail without model markup.",
);
assert(
  inlineCitation.includes("<HoverCard") &&
    inlineCitation.includes("<HoverCardTrigger") &&
    inlineCitation.includes("<HoverCardContent") &&
    inlineCitation.includes("<Carousel") &&
    inlineCitation.includes("new URL(sources[0]).hostname"),
  "The official citation pill must open its source carousel on hover.",
);
assert(
  /memo\(function AgentAssistantMessageRow/.test(presentation) &&
    presentation.includes("AgentMessageTimeline") &&
    presentation.includes("AgentChangeSummary") &&
    /lazy\(\(\)\s*=>\s*import\("\.\/copilot-change-summary"\)\)/.test(
      presentation,
    ) &&
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
const toolDetailsDisclosureClass = toolPresentation.match(
  /className="(?<classes>group\/details[^"]+)"/,
);
assert(
  toolDetailsDisclosureClass?.groups?.classes.includes("shadow-none") &&
    toolDetailsDisclosureClass.groups.classes.includes(
      "hover:bg-transparent",
    ) &&
    toolDetailsDisclosureClass.groups.classes.includes("hover:shadow-none"),
  "Completed-tool disclosure must stay flat instead of gaining a hover surface or shadow.",
);
assert(
  /<AgentMessageTimeline[\s\S]{0,300}isStreamingAssistant=\{isStreamingAssistant\}/.test(
    presentation,
  ) &&
    toolPresentation.includes("shouldShowTimelineContinuationStatus(") &&
    toolPresentation.includes("label={t.agentToolContinuing}"),
  "A streaming timeline that pauses after completed tools must keep a shimmer status visible.",
);
assert(
  /export function AgentChangeSummary/.test(changeSummary) &&
    changeSummary.includes("getAgentEditDiffFields") &&
    changeSummary.includes("getAgentQualityWarnings") &&
    changeSummary.includes("draftDiffs?.map") &&
    changeSummary.includes("visibleDiffs ?? responseDiffs") &&
    presentation.includes("draftDiffs={draftDiffs}") &&
    conversationView.includes(
      "draft.state?.sourceMessageId === message.id",
    ),
  "Change-summary decoding and quality warnings must stay behind the summary seam.",
);
assert(
  /export function AgentUserMessageRow/.test(userMessageRow) &&
    userMessageRow.includes("<AgentMessageAttachments") &&
    userMessageRow.includes("const canRetry") &&
    userMessageRow.includes("message.execution?.status") &&
    userMessageRow.includes("tooltip={t.agentRetry}") &&
    userMessageRow.includes("onClick={onRetry}") &&
    !userMessageRow.includes('role="status"') &&
    !userMessageRow.includes("agentRunFailed") &&
    !userMessageRow.includes("agentRunCancelled") &&
    !userMessageRow.includes("agentProviderTimeout"),
  "User messages must keep retry available as a hover action without rendering a persistent terminal-status footer.",
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
