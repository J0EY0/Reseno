import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
import { findNodes, getMemberPath, parseSource } from "./source-analysis.mjs";
import { evaluateTypeScript } from "./typescript-module.mjs";

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
  readFile(
    new URL("components/ai-elements/prompt-input.tsx", sourceRoot),
    "utf8",
  ),
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
const latestUserMessage = findNodes(
  parseSource(conversationView),
  ts.isVariableDeclaration,
).find(
  (node) => getMemberPath(node.name) === "latestUserMessageId",
)?.initializer;
assert.ok(latestUserMessage);
const { selectLatestUser } = evaluateTypeScript(
  `export const selectLatestUser = (messages) => ${latestUserMessage.getText()};`,
);
assert.equal(
  selectLatestUser([
    { id: "old-user", role: "user" },
    { id: "assistant", role: "assistant" },
    { id: "current-user", role: "user" },
    { id: "partial", role: "assistant" },
  ]),
  "current-user",
  "A partial assistant response must not take ownership of Retry.",
);
assert.equal(
  selectLatestUser([{ id: "assistant", role: "assistant" }]),
  undefined,
);
assert.match(
  conversationView,
  /retryable=\{message\.id === latestUserMessageId\}/,
);

assert(
  messageResponse.includes('from "streamdown"') &&
    messageResponse.includes('from "@streamdown/math"') &&
    messageResponse.includes('from "@streamdown/mermaid"'),
  "The optional response module must retain the existing rich rendering plugins.",
);
assert(
  /const richMessageResponsePromise\s*=\s*import\([\s\S]*?"@\/components\/ai-elements\/message-response"[\s\S]*?lazy\(\(\)\s*=>\s*richMessageResponsePromise\)/.test(
    responseContent,
  ) && responseContent.includes('isStreaming ? "invisible" : undefined'),
  "The Agent panel must preload its optional rich renderer without exposing a plain-text streaming fallback.",
);
assert(
  appStyles.includes('@import "streamdown/styles.css";') &&
    appStyles.includes("animation-delay: min(var(--sd-delay, 0ms), 240ms);"),
  "Streamdown animation styles must load with a bounded reveal delay.",
);
assert(
  assistantResponse.includes("isStreaming") &&
    /isStreaming\s*\|\|\s*!isPlainAgentText\(text\)/.test(assistantResponse) &&
    /AgentPlainResponse/.test(assistantResponse) &&
    /AgentRichResponse[\s\S]{0,120}text=\{text\}/.test(assistantResponse),
  "Settled plain responses must stay lightweight while active streaming text uses the optional animated renderer.",
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
    changeSummary.includes("getAgentQualityWarnings") &&
    changeSummary.includes('data-slot="agent-draft-resolution-receipt"') &&
    changeSummary.includes('item.status === "pending"') &&
    !changeSummary.includes("onApplyAgentDraft") &&
    !conversationView.includes("shouldShowAgentDraftActions"),
  "Message history must keep only resolved receipts and compact quality warnings behind its summary seam.",
);
assert(
  /function AgentUserMessageRow/.test(userMessageRow) &&
    userMessageRow.includes("<AgentMessageAttachments") &&
    userMessageRow.includes("const canRetry") &&
    userMessageRow.includes("message.execution?.status") &&
    userMessageRow.includes("tooltip={t.agentRetry}") &&
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
  ) && promptInput.includes("usePromptInputForm"),
  "PromptInput must retain only its used form primitives behind the deep form hook.",
);

console.log("Agent rendering bundle boundaries verified.");
