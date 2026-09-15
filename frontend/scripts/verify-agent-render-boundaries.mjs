import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const [
  packageManifest,
  messagePrimitives,
  messageResponse,
  presentation,
  toolPresentation,
  promptInput,
  shimmer,
  appStyles,
] = await Promise.all(
  [
    "../package.json",
    "components/ai-elements/message.tsx",
    "components/ai-elements/message-response.tsx",
    "components/copilot/copilot-message-presentation.tsx",
    "components/copilot/copilot-tool-presentation.tsx",
    "components/ai-elements/prompt-input.tsx",
    "components/ai-elements/shimmer.tsx",
    "index.css",
  ].map((path) => readFile(new URL(`../src/${path}`, import.meta.url), "utf8")),
);

const responseContent = await readFile(
  new URL(
    "../src/components/copilot/copilot-response-content.tsx",
    import.meta.url,
  ),
  "utf8",
);
assert.match(
  responseContent,
  /const richMessageResponsePromise\s*=\s*import\([\s\S]*?"@\/components\/ai-elements\/message-response"[\s\S]*?lazy\(\(\)\s*=>\s*richMessageResponsePromise\)/,
  "The Agent module must preload its optional rich renderer.",
);

const agentThreadScrollRule = appStyles.match(
  /\.agent-thread-scroll\s*\{(?<body>[\s\S]*?)\n\}/,
);

const toolDetailsDisclosureClass = toolPresentation.match(
  /className="(?<classes>group\/details[^"]+)"/,
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
  messageResponse.includes('from "streamdown"') &&
    messageResponse.includes('from "@streamdown/math"') &&
    messageResponse.includes('from "@streamdown/mermaid"'),
  "The optional response module must retain the existing rich rendering plugins.",
);

assert(
  appStyles.includes('@import "streamdown/styles.css";') &&
    appStyles.includes("animation-delay: min(var(--sd-delay, 0ms), 240ms);"),
  "Streamdown animation styles must load with a bounded reveal delay.",
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

assert(
  toolDetailsDisclosureClass?.groups?.classes.includes("shadow-none") &&
    toolDetailsDisclosureClass.groups.classes.includes(
      "hover:bg-transparent",
    ) &&
    toolDetailsDisclosureClass.groups.classes.includes("hover:shadow-none"),
  "Completed-tool disclosure must stay flat instead of gaining a hover surface or shadow.",
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
