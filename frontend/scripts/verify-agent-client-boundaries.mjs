import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { join } from "node:path";
const sourceRoot = new URL("../src/", import.meta.url).pathname;

await assert.rejects(
  access(join(sourceRoot, "lib", "agent-api.ts")),
  (error) => error?.code === "ENOENT",
  "The retired Agent API facade must not be restored.",
);

const [
  panelSource,
  attachmentPolicySource,
  promptActionsSource,
  messageActionsSource,
  conversationSource,
  sessionHydrationSource,
  runStreamSource,
  sendControllerSource,
] = await Promise.all([
  readFile(
    join(sourceRoot, "components", "copilot", "copilot-panel.tsx"),
    "utf8",
  ),
  readFile(
    join(sourceRoot, "components", "copilot", "copilot-attachment-policy.ts"),
    "utf8",
  ),
  readFile(
    join(sourceRoot, "components", "copilot", "use-agent-prompt-actions.ts"),
    "utf8",
  ),
  readFile(
    join(sourceRoot, "components", "copilot", "use-agent-message-actions.ts"),
    "utf8",
  ),
  readFile(
    join(sourceRoot, "components", "copilot", "use-agent-conversation.ts"),
    "utf8",
  ),
  readFile(
    join(sourceRoot, "components", "copilot", "use-agent-session-hydration.ts"),
    "utf8",
  ),
  readFile(
    join(sourceRoot, "components", "copilot", "use-agent-run-stream.ts"),
    "utf8",
  ),
  readFile(
    join(sourceRoot, "components", "copilot", "use-agent-send-controller.ts"),
    "utf8",
  ),
]);
const controllerSources = [
  promptActionsSource,
  messageActionsSource,
  conversationSource,
  sessionHydrationSource,
  runStreamSource,
  sendControllerSource,
].join("\n");
assert.doesNotMatch(
  `${panelSource}\n${attachmentPolicySource}\n${controllerSources}`,
  /@\/lib\/agent-api/,
  "Agent callers must import the responsible client directly, not a facade.",
);
assert.doesNotMatch(
  panelSource,
  /@\/lib\/agent-(?:attachment|session-run|stream)-client/,
  "The CopilotPanel orchestration entry must not own transport details.",
);
assert.match(promptActionsSource, /@\/lib\/agent-attachment-client/);
assert.match(messageActionsSource, /@\/lib\/agent-attachment-client/);
assert.match(
  `${conversationSource}\n${sessionHydrationSource}\n${runStreamSource}\n${sendControllerSource}`,
  /@\/lib\/agent-session-run-client/,
);
assert.match(
  `${sessionHydrationSource}\n${sendControllerSource}`,
  /@\/lib\/agent-stream-client/,
);

console.log("Agent client import boundaries verified.");
