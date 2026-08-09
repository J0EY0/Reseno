import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { join } from "node:path";
import vm from "node:vm";
import * as ts from "typescript";

const frontendRoot = new URL("..", import.meta.url).pathname;
const sourceRoot = join(frontendRoot, "src");
const apiCalls = [];

const apiClient = {
  apiRoutes: {
    agentAttachment: (resumeId, attachmentId) =>
      `/api/agent/resumes/${resumeId}/attachments/${attachmentId}`,
    agentAttachments: "/api/agent/attachments",
    agentResumeRun: (resumeId) => `/api/agent/resumes/${resumeId}/run`,
    agentResumeSession: (resumeId) => `/api/agent/resumes/${resumeId}/session`,
    agentRun: (runId) => `/api/agent/runs/${runId}`,
  },
  fetchApiResource: (url, options) => {
    apiCalls.push({ kind: "fetch", options, route: url });
    return Promise.resolve({ ok: true });
  },
  requestApi: (route, options = {}) => {
    apiCalls.push({ kind: "request", options, route });
    return Promise.resolve({});
  },
  resolveApiUrl: (route) => `http://agent.test${route}`,
  uploadApi: (route, body, options = {}) => {
    apiCalls.push({ body, kind: "upload", options, route });
    return Promise.resolve({ id: "attachment-test" });
  },
};

async function loadTypeScriptModule(fileName) {
  const source = await readFile(join(sourceRoot, "lib", fileName), "utf8");
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
    require: (specifier) => {
      if (specifier === "@/lib/api-client") {
        return apiClient;
      }
      throw new Error(`Unexpected import: ${specifier}`);
    },
  });

  return module.exports;
}

function takeLastCall(kind) {
  const call = apiCalls.at(-1);
  assert.equal(call?.kind, kind);
  return call;
}

const [attachmentClient, sessionRunClient] = await Promise.all([
  loadTypeScriptModule("agent-attachment-client.ts"),
  loadTypeScriptModule("agent-session-run-client.ts"),
]);

{
  const controller = new AbortController();
  await sessionRunClient.loadActiveAgentRun("resume-run", {
    signal: controller.signal,
  });
  let call = takeLastCall("request");
  assert.equal(call.route, "/api/agent/resumes/resume-run/run");
  assert.equal(call.options.signal, controller.signal);

  await sessionRunClient.stopAgentRun("run-stop");
  call = takeLastCall("request");
  assert.equal(call.route, "/api/agent/runs/run-stop");
  assert.equal(call.options.method, "DELETE");

  await sessionRunClient.loadAgentSession("resume-session", {
    signal: controller.signal,
  });
  call = takeLastCall("request");
  assert.equal(call.route, "/api/agent/resumes/resume-session/session");
  assert.equal(call.options.cacheTtlMs, 0);
  assert.equal(call.options.signal, controller.signal);

  const replacement = { messages: [], revision: 7 };
  await sessionRunClient.replaceAgentSession("resume-session", replacement);
  call = takeLastCall("request");
  assert.equal(call.route, "/api/agent/resumes/resume-session/session");
  assert.equal(call.options.body, replacement);
  assert.equal(call.options.method, "PUT");
}

{
  const controller = new AbortController();
  const body = new FormData();
  const onProgress = () => {};
  await attachmentClient.uploadAgentAttachment(body, "resume-attachment", {
    onProgress,
    signal: controller.signal,
  });
  let call = takeLastCall("upload");
  assert.equal(call.route, "/api/agent/attachments");
  assert.equal(call.body, body);
  assert.equal(body.get("resumeId"), "resume-attachment");
  assert.equal(call.options.onProgress, onProgress);
  assert.equal(call.options.signal, controller.signal);

  await attachmentClient.downloadAgentAttachment(
    "resume-attachment",
    "attachment-download",
  );
  call = takeLastCall("fetch");
  assert.equal(
    call.route,
    "http://agent.test/api/agent/resumes/resume-attachment/attachments/attachment-download",
  );
  assert.equal(call.options.cache, "no-store");

  await attachmentClient.deletePendingAgentAttachment(
    "resume-attachment",
    "attachment-delete",
  );
  call = takeLastCall("request");
  assert.equal(
    call.route,
    "/api/agent/resumes/resume-attachment/attachments/attachment-delete",
  );
  assert.equal(call.options.method, "DELETE");
}

const moduleNames = [
  "agent-attachment-client.ts",
  "agent-message-codec.ts",
  "agent-session-run-client.ts",
  "agent-stream-client.ts",
];
const moduleSources = await Promise.all(
  moduleNames.map((name) => readFile(join(sourceRoot, "lib", name), "utf8")),
);
for (const [index, source] of moduleSources.entries()) {
  assert.ok(
    source.trimEnd().split(/\r?\n/).length <= 600,
    `${moduleNames[index]} must stay within the TypeScript source budget.`,
  );
}
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
  readFile(join(sourceRoot, "components", "copilot", "copilot-panel.tsx"), "utf8"),
  readFile(
    join(
      sourceRoot,
      "components",
      "copilot",
      "copilot-attachment-policy.ts",
    ),
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

console.log("Agent client boundaries and request semantics verified.");
