import { readFile } from "node:fs/promises";
import { join } from "node:path";
import vm from "node:vm";
import * as ts from "typescript";

const frontendRoot = new URL("..", import.meta.url).pathname;
const copilotRoot = join(
  frontendRoot,
  "src",
  "components",
  "copilot",
);
const runtimePath = join(copilotRoot, "agent-conversation-runtime.ts");
const [runtimeSource, conversationSource, sendControllerSource] =
  await Promise.all([
    readFile(runtimePath, "utf8"),
    readFile(join(copilotRoot, "use-agent-conversation.ts"), "utf8"),
    readFile(join(copilotRoot, "use-agent-send-controller.ts"), "utf8"),
  ]);
const sourceFile = ts.createSourceFile(
  runtimePath,
  runtimeSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function findFunctionDeclaration(name) {
  let match;

  function visit(node) {
    if (
      ts.isFunctionDeclaration(node) &&
      node.name?.text === name
    ) {
      match = node;
      return;
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return match;
}

function extractBetween(source, start, end) {
  const startIndex = source.indexOf(start);
  const endIndex = source.indexOf(end, startIndex + start.length);

  assert(startIndex >= 0 && endIndex > startIndex, `Missing source range: ${start}`);
  return source.slice(startIndex, endIndex);
}

const ownershipDeclaration = findFunctionDeclaration("isPendingSendOwner");
assert(
  ownershipDeclaration,
  "The Agent panel must define a single ownership check for provisional messages.",
);

const ownershipSource = ownershipDeclaration.getText(sourceFile);
const compiledOwnership = ts.transpileModule(
  `${ownershipSource}\nmodule.exports = { isPendingSendOwner };`,
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  },
).outputText;
const ownershipModule = { exports: {} };
vm.runInNewContext(compiledOwnership, {
  exports: ownershipModule.exports,
  module: ownershipModule,
});
const { isPendingSendOwner } = ownershipModule.exports;

assert(
  isPendingSendOwner("user-1", "user-1", "resume-1", "resume-1"),
  "The send that published a provisional message must own its rollback.",
);
assert(
  !isPendingSendOwner(null, "user-1", "resume-1", "resume-1"),
  "An authoritative refresh must revoke provisional rollback ownership.",
);
assert(
  !isPendingSendOwner("user-2", "user-1", "resume-1", "resume-1"),
  "An older send must not roll back a newer provisional message.",
);
assert(
  !isPendingSendOwner("user-1", "user-1", "resume-1", "resume-2"),
  "A send must not roll back messages from another resume session.",
);

const refreshSource = extractBetween(
  conversationSource,
  "const refreshAgentSession = useCallback(",
  "const consumeRunStream = useAgentRunStream(",
);
assert(
  refreshSource.includes("runtime.optimisticMessageOwner = null"),
  "Replacing messages from the server must revoke provisional ownership.",
);

const cancelSource = extractBetween(
  sendControllerSource,
  "const cancelScheduledSend = useCallback(",
  "const stopResponding = useCallback(",
);
assert(
  cancelSource.includes("isPendingSendOwner("),
  "Scheduled-send cancellation must verify rollback ownership.",
);

const stopSource = extractBetween(
  sendControllerSource,
  "const stopResponding = useCallback(",
  "const sendPrompt:",
);
assert(
  stopSource.includes("cancelScheduledSend(true)"),
  "Stopping during debounce must remove the provisional user message.",
);

const sendSource = extractBetween(
  sendControllerSource,
  "const sendPrompt:",
  "\n  useEffect(() => {",
);
assert(
  sendSource.includes("runtime.optimisticMessageOwner = userMessage.id"),
  "Publishing a provisional user message must claim rollback ownership.",
);
assert(
  sendSource.includes("isPendingSendOwner("),
  "A failed send must verify ownership before restoring old messages.",
);

let owner = "user-1";
let messages = ["persisted", "user-1"];
const rollbackMessages = ["persisted"];
messages = ["persisted", "server-authoritative"];
owner = null;
if (isPendingSendOwner(owner, "user-1", "resume-1", "resume-1")) {
  messages = rollbackMessages;
}
assert(
  messages.join(",") === "persisted,server-authoritative",
  "A late failed rollback must not overwrite authoritative session history.",
);

owner = "user-1";
messages = ["persisted", "user-1"];
if (isPendingSendOwner(owner, "user-1", "resume-1", "resume-1")) {
  messages = rollbackMessages;
}
assert(
  messages.join(",") === "persisted",
  "Stopping a debounced send must restore the pre-send message list.",
);

console.log("Agent panel race checks passed.");
