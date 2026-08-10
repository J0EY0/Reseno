import { readFile } from "node:fs/promises";
import { join } from "node:path";
import vm from "node:vm";
import * as ts from "typescript";

const frontendRoot = new URL("..", import.meta.url).pathname;
const repositoryRoot = join(frontendRoot, "..");

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

function tool(name, state, overrides = {}) {
  return {
    id: overrides.id ?? `call-${name}`,
    type: `tool-${name}`,
    title: name,
    state,
    ...overrides,
  };
}

const messageCodec = await loadTypeScriptModule(
  join(frontendRoot, "src", "lib", "agent-message-codec.ts"),
);
const toolDisplay = await loadTypeScriptModule(
  join(frontendRoot, "src", "lib", "agent-tool-display.ts"),
);

{
  let message = {
    id: "assistant-message",
    role: "assistant",
    text: "",
    tools: [],
  };
  const started = tool("resume_analysis", "input-streaming", {
    input: { target: "resume" },
  });
  const progressed = tool("resume_analysis", "input-available", {
    input: { target: "resume" },
  });
  const completed = tool("resume_analysis", "output-available", {
    completedAt: "2026-07-26T10:00:00Z",
    output: { score: 90 },
  });

  message = messageCodec.applyAgentToolStreamEvent(message, { tool: started });
  message = messageCodec.applyAgentToolStreamEvent(message, { tool: progressed });
  message = messageCodec.applyAgentToolStreamEvent(message, { tool: completed });
  message = messageCodec.applyAgentToolStreamEvent(message, { tool: completed });

  assert(
    message.tools.length === 1,
    "Repeated tool events must update one invocation instead of duplicating it.",
  );
  assert(
    message.tools[0].state === "output-available" &&
      message.tools[0].output.score === 90,
    "tool_done must preserve the terminal state and output.",
  );

  message = messageCodec.applyAgentToolStreamEvent(message, {
    tool: tool("edit_plan", "input-streaming"),
  });
  const reconciled = messageCodec.mergeAgentToolInvocations(message.tools, [
    tool("edit_plan", "output-available", { output: { editCount: 2 } }),
    tool("resume_analysis", "input-available"),
  ]);

  assert(
    reconciled.map((item) => item.id).join(",") ===
      "call-resume_analysis,call-edit_plan",
    "A snapshot must reconcile by id without changing first-seen order.",
  );
  assert(
    reconciled[0].state === "output-available",
    "A late snapshot must not regress a completed invocation.",
  );
  assert(
    reconciled[1].output.editCount === 2,
    "A full snapshot must still reconcile the latest tool output.",
  );
}

{
  const registrySource = await readFile(
    join(
      repositoryRoot,
      "backend",
      "app",
      "services",
      "agent",
      "tools",
      "registry.py",
    ),
    "utf8",
  );
  const backendToolNames = Array.from(
    registrySource.matchAll(/AgentToolSpec\(\s*"([^"]+)"/g),
    (match) => match[1],
  );
  const frontendToolNames = Array.from(
    toolDisplay.REGISTERED_AGENT_TOOL_NAMES,
  );

  assert(
    backendToolNames.length === 15,
    `Expected 15 backend Agent tools, found ${backendToolNames.length}.`,
  );
  assert(
    JSON.stringify([...frontendToolNames].sort()) ===
      JSON.stringify([...backendToolNames].sort()),
    "Frontend tool display metadata must cover every registered backend tool.",
  );

  for (const name of backendToolNames) {
    const invocation = tool(name, "input-streaming");
    assert(
      toolDisplay.getAgentToolName(invocation) === name,
      `Tool ${name} must resolve from its backend invocation type.`,
    );
    for (const phase of ["running", "complete", "error"]) {
      assert(
        toolDisplay.getAgentToolLabelKey(invocation, phase).startsWith(
          "agentTool",
        ),
        `Tool ${name} must have a ${phase} label fallback.`,
      );
    }
  }

  assert(
    toolDisplay.getAgentToolDisplayCategory(
      tool("web_fetch", "input-streaming", { input: { purpose: "jd" } }),
    ) === "fetch-job-reference",
    "JD fetches must retain their dedicated user-facing status.",
  );
  assert(
    toolDisplay.getAgentToolDisplayCategory(
      tool("edit_merge_items", "input-streaming"),
    ) === "generate-draft",
    "Resume mutation tools must use the draft-generation status.",
  );
  assert(
    toolDisplay.isAgentEditExecutionTool(
      tool("edit_execute", "output-available"),
    ),
    "Edit observations must be recognized through centralized tool metadata.",
  );
  assert(
    toolDisplay.isToolError(tool("edit_execute", "output-error").state) &&
      toolDisplay.isToolError(tool("edit_execute", "output-denied").state) &&
      !toolDisplay.isToolError(tool("edit_execute", "output-available").state),
    "Terminal tool failures must remain distinguishable from successful actions.",
  );
  assert(
    toolDisplay.isToolFailure(
      tool("edit_execute", "output-available", {
        output: { editCount: 0, rejectedEditCount: 1 },
      }),
    ) &&
      !toolDisplay.isToolFailure(
        tool("edit_execute", "output-available", {
          output: { editCount: 1, rejectedEditCount: 0 },
        }),
      ),
    "Structured edit rejection must be displayed as a failed tool outcome.",
  );

  const unknownTool = tool("future_tool", "input-streaming");
  assert(
    toolDisplay.getAgentToolDisplayCategory(unknownTool) === "processing" &&
      toolDisplay.getAgentToolLabelKey(unknownTool, "complete") ===
        "agentToolProcessingDone",
    "Unknown future tools must use the generic processing fallback.",
  );
}

console.log("Agent tool stream and display metadata checks passed.");
