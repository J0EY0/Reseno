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
const sendControllerPath = join(copilotRoot, "use-agent-send-controller.ts");
const promptFormPath = join(
  frontendRoot,
  "src",
  "components",
  "ai-elements",
  "use-prompt-input-form.ts",
);
const [
  runtimeSource,
  conversationSource,
  sendControllerSource,
  runStreamSource,
  promptFormSource,
  promptActionsSource,
  hydrationSource,
  conversationViewSource,
  composerSource,
  panelSource,
  panelTypesSource,
  agentHostSource,
  agentMotionStylesSource,
  agentLayoutSource,
  workspaceViewSource,
  workspaceHeaderSource,
  headerActionsSource,
  appStylesSource,
] =
  await Promise.all([
    readFile(runtimePath, "utf8"),
    readFile(join(copilotRoot, "use-agent-conversation.ts"), "utf8"),
    readFile(sendControllerPath, "utf8"),
    readFile(join(copilotRoot, "use-agent-run-stream.ts"), "utf8"),
    readFile(promptFormPath, "utf8"),
    readFile(join(copilotRoot, "use-agent-prompt-actions.ts"), "utf8"),
    readFile(join(copilotRoot, "use-agent-session-hydration.ts"), "utf8"),
    readFile(join(copilotRoot, "copilot-conversation-view.tsx"), "utf8"),
    readFile(join(copilotRoot, "copilot-composer.tsx"), "utf8"),
    readFile(join(copilotRoot, "copilot-panel.tsx"), "utf8"),
    readFile(join(copilotRoot, "copilot-panel-types.ts"), "utf8"),
    readFile(
      join(
        frontendRoot,
        "src",
        "components",
        "workspace",
        "resume-detail-agent-host.tsx",
      ),
      "utf8",
    ),
    readFile(
      join(
        frontendRoot,
        "src",
        "components",
        "workspace",
        "resume-detail-agent-motion.css",
      ),
      "utf8",
    ),
    readFile(
      join(
        frontendRoot,
        "src",
        "components",
        "workspace",
        "use-resume-detail-agent-layout.ts",
      ),
      "utf8",
    ),
    readFile(
      join(
        frontendRoot,
        "src",
        "components",
        "workspace",
        "resume-detail-workspace-view.tsx",
      ),
      "utf8",
    ),
    readFile(
      join(
        frontendRoot,
        "src",
        "components",
        "workspace",
        "resume-detail-workspace-header.tsx",
      ),
      "utf8",
    ),
    readFile(
      join(
        frontendRoot,
        "src",
        "components",
        "workspace",
        "resume-detail-header-actions.tsx",
      ),
      "utf8",
    ),
    readFile(join(frontendRoot, "src", "index.css"), "utf8"),
  ]);
const sourceFile = ts.createSourceFile(
  runtimePath,
  runtimeSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);
const promptFormSourceFile = ts.createSourceFile(
  promptFormPath,
  promptFormSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TS,
);
const sendControllerSourceFile = ts.createSourceFile(
  sendControllerPath,
  sendControllerSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TS,
);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function findFunctionDeclaration(source, name) {
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

  visit(source);
  return match;
}

function compileFunctions(source, declarations, names) {
  for (const declaration of declarations) {
    assert(declaration, `Missing behavior function: ${names.join(", ")}`);
  }
  const compiled = ts.transpileModule(
    `${declarations.map((declaration) => declaration.getText(source)).join("\n")}\nmodule.exports = { ${names.join(", ")} };`,
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText;
  const behaviorModule = { exports: {} };
  vm.runInNewContext(compiled, {
    exports: behaviorModule.exports,
    module: behaviorModule,
  });
  return behaviorModule.exports;
}

async function loadTypeScriptModule(path, imports, globals = {}) {
  const source = await readFile(path, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const behaviorModule = { exports: {} };
  vm.runInNewContext(compiled, {
    AbortController,
    console,
    exports: behaviorModule.exports,
    module: behaviorModule,
    require: (specifier) => {
      if (Object.hasOwn(imports, specifier)) {
        return imports[specifier];
      }
      throw new Error(`Unexpected import: ${specifier}`);
    },
    ...globals,
  });
  return behaviorModule.exports;
}

function createDeferred() {
  let reject;
  let resolve;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    reject = rejectPromise;
    resolve = resolvePromise;
  });
  return { promise, reject, resolve };
}

async function flushAsyncWork() {
  await new Promise((resolve) => setImmediate(resolve));
}

function extractBetween(source, start, end) {
  const startIndex = source.indexOf(start);
  const endIndex = source.indexOf(end, startIndex + start.length);

  assert(startIndex >= 0 && endIndex > startIndex, `Missing source range: ${start}`);
  return source.slice(startIndex, endIndex);
}

const ownershipDeclaration = findFunctionDeclaration(
  sourceFile,
  "isPendingSendOwner",
);
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

const promptBehaviorNames = [
  "selectActivePromptSubmissionFiles",
  "shouldClearPromptSubmissionText",
];
const promptBehavior = compileFunctions(
  promptFormSourceFile,
  promptBehaviorNames.map((name) =>
    findFunctionDeclaration(promptFormSourceFile, name),
  ),
  promptBehaviorNames,
);
const preflightBehaviorNames = [
  "waitForAgentSendPreflight",
  "ownsAgentSendPreflight",
];
const preflightBehavior = compileFunctions(
  sendControllerSourceFile,
  preflightBehaviorNames.map((name) =>
    findFunctionDeclaration(sendControllerSourceFile, name),
  ),
  preflightBehaviorNames,
);

let finishPreferenceFlush;
const preferenceFlush = new Promise((resolve) => {
  finishPreferenceFlush = resolve;
});
const cancelledPreflight = new AbortController();
let activePreflight = cancelledPreflight;
const preflightResult = preflightBehavior.waitForAgentSendPreflight(
  preferenceFlush,
  cancelledPreflight.signal,
);
cancelledPreflight.abort();
activePreflight = null;
const canPostAfterStop =
  (await preflightResult) &&
  preflightBehavior.ownsAgentSendPreflight(
    activePreflight,
    cancelledPreflight,
  );
let postCount = 0;
if (canPostAfterStop) {
  postCount += 1;
}
finishPreferenceFlush();
await preferenceFlush;
assert(
  !canPostAfterStop && postCount === 0,
  "Stopping during preference flush must settle preflight as cancelled and prevent the POST.",
);

const completedPreflight = new AbortController();
assert(
  (await preflightBehavior.waitForAgentSendPreflight(
    Promise.resolve(),
    completedPreflight.signal,
  )) &&
    preflightBehavior.ownsAgentSendPreflight(
      completedPreflight,
      completedPreflight,
    ),
  "A completed preference flush may proceed only while it still owns preflight.",
);
const capturedFiles = [
  { id: "removed", filename: "removed.pdf" },
  { id: "captured", filename: "captured.pdf" },
];
const currentFiles = [
  { id: "captured", filename: "captured.pdf" },
  { id: "new", filename: "new.pdf" },
];
assert(
  promptBehavior
    .selectActivePromptSubmissionFiles(capturedFiles, currentFiles)
    .map((file) => file.id)
    .join(",") === "captured",
  "Submission must exclude a removed file and must not absorb a newly added file.",
);
assert(
  promptBehavior.shouldClearPromptSubmissionText("captured", "captured"),
  "An accepted submission may clear the exact text snapshot it sent.",
);
assert(
  !promptBehavior.shouldClearPromptSubmissionText("captured", "new text"),
  "An accepted submission must preserve text typed after the snapshot.",
);

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

const adoptionSource = extractBetween(
  conversationSource,
  "const adoptAgentSession = useCallback(",
  "const refreshAgentSession = useCallback(",
);
assert(
  adoptionSource.includes("runtime.optimisticMessageOwner = null"),
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
  stopSource.includes("cancelAgentSendPreflight()") &&
    stopSource.includes("cancelScheduledSend(true)"),
  "Stopping must cancel preference preflight before handling a debounced send.",
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
assert(
  sendControllerSource.includes("accepted: acceptedPromise"),
  "The send interface must expose server acceptance separately from completion.",
);
assert(
  /preflightAbortRef\.current\s*=\s*preflightAbortController[\s\S]{0,500}await waitForAgentSendPreflight\([\s\S]{0,500}ownsAgentSendPreflight\(/.test(
    sendSource,
  ) &&
    /await runtime\.sessionReadyPromise\s*\n\s*if \(\s*!ownsAgentSendPreflight\(/.test(
      sendSource,
    ) &&
    /await refreshAgentSession\(resumeId, true\)[\s\S]{0,240}!ownsAgentSendPreflight\(/.test(
      sendSource,
    ) &&
    /return \(\) => \{[\s\S]*cancelAgentSendPreflight\(\)[\s\S]*runtime\.activeRequestAbort\?\.abort\(\)/.test(
      sendControllerSource,
    ),
  "Preference preflight ownership must be registered before awaits and rechecked until debounce owns cancellation.",
);
assert(
  sendControllerSource.includes("throwOnFailure: true") &&
    runStreamSource.includes("if (throwOnFailure)") &&
    runStreamSource.includes("throw error"),
  "Chat-start errors must reach the send controller so 409 reconciliation is behavioral.",
);
assert(
  sendControllerSource.includes("if (resumeId && !expectedRevision)"),
  "Every resume-scoped Agent request must load a revision before sending.",
);
assert(
  !sendControllerSource.includes("runtime.sessionRevision ?? undefined"),
  "A resume-scoped Agent request must never fall back to an undefined revision.",
);
assert(
  promptActionsSource.includes("await sendOperation.accepted"),
  "The composer must remain populated until the server accepts the run.",
);
assert(
  promptFormSource.includes("selectActivePromptSubmissionFiles("),
  "Prompt submission must reconcile its captured files with current attachments.",
);
assert(
  promptFormSource.includes("shouldClearPromptSubmissionText("),
  "Prompt submission must clear only the text snapshot that was accepted.",
);
assert(
  /const mountedRef = useRef\(false\)/.test(promptFormSource) &&
    /useEffect\(\(\) => \{\s*mountedRef\.current = true;\s*return \(\) => \{\s*mountedRef\.current = false;\s*\};\s*\}, \[\]\)/.test(
      promptFormSource,
    ) &&
    /const convertedFiles = await Promise\.all\([\s\S]*?if \(!mountedRef\.current\) \{\s*return;\s*\}[\s\S]*?const result = onSubmit\(/.test(
      promptFormSource,
    ) &&
    /if \(result instanceof Promise\) \{\s*await result;\s*\}\s*for \(const \{ id \} of activeFiles\)/.test(
      promptFormSource,
    ) &&
    !/await result;\s*\}\s*if \(!mountedRef\.current\)/.test(
      promptFormSource,
    ),
  "Unmounting must block a stale submit before request start but preserve captured cleanup after server acceptance.",
);
assert(
  hydrationSource.includes("setSessionReady(false)"),
  "Agent bootstrap must close the send gate before loading session state.",
);
assert(
  hydrationSource.includes("runtime.sessionReady = true"),
  "Agent bootstrap must open the send gate only after all bootstrap reads succeed.",
);
assert(
  /catch \(error\) \{\s*if \(!isAbortError\(error\)\) \{[\s\S]{0,500}if \(runtime\.currentResumeId === expectedResumeId\) \{[\s\S]{0,300}runtime\.sessionRevision = null[\s\S]{0,180}runtime\.sessionReady = false[\s\S]{0,180}updates\.setSessionReady\(false\)[\s\S]{0,180}updates\.setSessionLoadError\(true\)/.test(
    runStreamSource,
  ),
  "A terminal refresh failure must invalidate only the still-current resume session and expose its load error.",
);
assert(
  /response\.messageDone\s*&&\s*\(\s*response\.status === ['"]completed['"]\s*\|\|\s*response\.status === ['"]cancelled['"]\s*\)/.test(
    runStreamSource,
  ),
  "A cancelled run with a durable message_done must keep its visible partial assistant message locally.",
);
assert(
  /finally \{[\s\S]*runtime\.activeRequestAbort === abortController[\s\S]*updates\.setStreamingMessage\(null\)[\s\S]*updates\.setIsResponding\(false\)/.test(
    runStreamSource,
  ),
  "Every observed terminal run must clear its owned streaming and responding state.",
);
assert(
  conversationViewSource.includes("AgentSessionLoadError"),
  "Bootstrap failures must remain visible even when history is non-empty.",
);
assert(
  composerSource.includes("isSessionReady"),
  "Composer controls must be disabled while Agent bootstrap is not ready.",
);
assert(
  /<PromptInputTextarea[\s\S]{0,700}aria-label=\{t\.agentPromptPlaceholderShort\}/.test(
    composerSource,
  ),
  "The Agent composer textarea must keep a localized accessible name even when its placeholder is empty.",
);
assert(
  agentHostSource.includes("inert={!shouldDockAgent}"),
  "A retained hidden dock must be inert.",
);
assert(
  panelSource.includes("const globalDropActive = !isPanelCollapsed"),
  "A retained hidden dock must not register a global file-drop target.",
);
assert(
  agentHostSource.includes("hasMountedAgent"),
  "The Agent controller must remain mounted after its first inline presentation.",
);

const desktopWorkspaceGridRule =
  appStylesSource.match(
    /@media\s*\(min-width:\s*1280px\)\s*\{[\s\S]*?\n\s*\.resume-workspace\s*\{([^}]*)\}/,
  )?.[1] ?? "";
const panelMotionRule =
  agentMotionStylesSource.match(
    /\.app-shell--document\s+\.agent-panel-motion-layer\s*\{([^}]*)\}/,
  )?.[1] ?? "";
const hiddenPanelMotionRule =
  agentMotionStylesSource.match(
    /\.agent-panel-dock\[aria-hidden='true'\]\s+\.agent-panel-motion-layer\s*\{([^}]*)\}/,
  )?.[1] ?? "";

assert(
  (`${appStylesSource}\n${agentMotionStylesSource}`.match(
    /transition(?:-property)?\s*:[^;{}]*\bgrid-template-columns\b/g,
  )?.length ?? 0) === 1 &&
    /--duration-move:\s*240ms/.test(appStylesSource) &&
    /--ease-move:\s*cubic-bezier\(0\.2,\s*0,\s*0,\s*1\)/.test(
      appStylesSource,
    ) &&
    /transition:\s*grid-template-columns\s+var\(--duration-move\)\s+var\(--ease-move\)/.test(
      desktopWorkspaceGridRule,
    ),
  "The desktop workspace must own the single tokenized 240ms grid-track transition.",
);
assert(
  workspaceViewSource.includes('"--agent-panel-width": "360px"'),
  "The desktop Agent motion layer must keep its final 360px width while the grid track clips it.",
);
assert(
  /className=\{cn\([\s\S]{0,180}agent-panel-dock[^\n]*overflow-hidden/.test(
    agentHostSource,
  ) &&
    /position:\s*absolute/.test(panelMotionRule) &&
    /left:\s*0/.test(panelMotionRule) &&
    !/right:\s*0/.test(panelMotionRule) &&
    /width:\s*var\(--agent-panel-width\)/.test(panelMotionRule) &&
    /opacity\s+var\(--duration-move\)\s+var\(--ease-move\)/.test(
      panelMotionRule,
    ) &&
    /transform\s+var\(--duration-move\)\s+var\(--ease-move\)/.test(
      panelMotionRule,
    ) &&
    /opacity:\s*0/.test(hiddenPanelMotionRule) &&
    /transform:\s*translateX\(12px\)/.test(hiddenPanelMotionRule) &&
    !/agent-panel-dock\s*\{[\s\S]{0,120}overflow:\s*visible/.test(
      agentMotionStylesSource,
    ),
  "The Agent surface must keep a fixed inner width while one 240ms timeline coordinates grid, transform, and opacity.",
);
assert(
  agentHostSource.includes("<CopilotPanelShell") &&
    agentHostSource.includes("<AgentPanelLoadingBody") &&
    agentHostSource.includes('data-slot="agent-panel-stable-loader"') &&
    agentHostSource.includes('data-slot="agent-panel-live-body"') &&
    agentHostSource.includes("<Suspense fallback={null}>") &&
    agentHostSource.includes("aria-hidden={showStableLoader}") &&
    agentHostSource.includes("inert={showStableLoader}") &&
    panelSource.includes("<CopilotPanelBodyFrame") &&
    /useLayoutEffect\(\(\) => \{\s*onStatusChange\(conversation\.status\)/.test(
      panelSource,
    ) &&
    !conversationViewSource.includes("<AgentSessionLoading"),
  "Lazy loading and session hydration must keep one visible loading body while the live panel mounts inertly behind it.",
);
assert(
  conversationViewSource.includes(
    "const INITIAL_AGENT_HISTORY_RENDER_COUNT = 10",
  ) &&
    conversationViewSource.includes(
      "const AGENT_HISTORY_RENDER_BATCH_SIZE = 6",
    ) &&
    conversationViewSource.includes("requestAnimationFrame(() =>") &&
    conversationViewSource.includes("startTransition(() =>") &&
    conversationViewSource.includes(
      "const renderedMessages = visibleMessages.slice(startIndex)",
    ) &&
    conversationViewSource.includes("renderedMessages.map((message)") &&
    panelSource.includes("key={conversation.sessionResetVersion}"),
  "Hydrated Agent history must render its newest messages first and progressively prepend older rows without trimming controller state.",
);
assert(
  panelTypesSource.includes("export type AgentPanelStatus") &&
    panelTypesSource.includes("onStatusChange: (status: AgentPanelStatus) => void") &&
    conversationSource.includes("status,") &&
    /onStatusChange\(conversation\.status\)/.test(panelSource) &&
    agentHostSource.includes('data-agent-status={panelStatus ?? "idle"}') &&
    agentHostSource.includes('className="agent-panel-toggle-status"') &&
    agentLayoutSource.includes("reportedStatus && reportedStatus.resumeId === resumeId"),
  "A retained conversation must report its low-frequency status to the collapsed Agent toggle without leaking across resumes.",
);
assert(
  /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*\*,\s*\*::before,\s*\*::after\s*\{[^}]*transition:\s*none\s*!important/.test(
    appStylesSource,
  ),
  "Reduced-motion users must not receive workspace or panel transitions.",
);
assert(
  !agentHostSource.includes("-${mode}"),
  "Collapsing the inline panel must not key-remount the Agent controller.",
);
assert(
  !workspaceHeaderSource.includes("messages.agentExpandPanel") &&
    headerActionsSource.includes("messages.agentExpandPanel") &&
    headerActionsSource.includes("messages.agentCollapsePanel") &&
    headerActionsSource.includes("commands.agent.setPanelCollapsed(") &&
    headerActionsSource.includes('data-slot="agent-compact-status-indicator"'),
  "Compact layouts must expose the same Agent state through the existing actions menu.",
);
assert(
  agentHostSource.includes("commands.agent.setPanelCollapsed(") &&
    agentHostSource.includes('data-slot="agent-panel-toggle"') &&
    agentHostSource.includes("aria-controls={RESUME_DETAIL_AGENT_PANEL_ID}") &&
    agentHostSource.includes("id={RESUME_DETAIL_AGENT_PANEL_ID}") &&
    agentHostSource.includes('"agent-panel-toggle relative hidden') &&
    agentHostSource.includes("xl:inline-flex") &&
    agentHostSource.includes("aria-expanded={") &&
    !agentHostSource.includes("aria-haspopup") &&
    agentHostSource.includes("onFocus={preloadCopilotPanelModule}") &&
    agentHostSource.includes("onPointerEnter={preloadCopilotPanelModule}"),
  "The canvas toolbar must toggle the accessible inline Agent panel and preload its lazy runtime.",
);
assert(
  !panelSource.includes("Sheet") &&
    !panelSource.includes("isSheetOpen") &&
    !panelTypesSource.includes("isSheetOpen") &&
    !agentHostSource.includes("setSheetOpen") &&
    !agentLayoutSource.includes("isSheetOpen") &&
    !appStylesSource.includes("agent-seam-rail"),
  "Agent presentation must not retain a Sheet or overlay state branch.",
);
assert(
  agentLayoutSource.includes(
    'const AGENT_AUTO_EXPAND_MEDIA_QUERY = "(min-width: 1536px)"',
  ) &&
    /useState\(\s*\(\)\s*=>\s*!window\.matchMedia\(AGENT_AUTO_EXPAND_MEDIA_QUERY\)\.matches,?\s*\)/.test(
      agentLayoutSource,
    ) &&
    !agentLayoutSource.includes("isDockLayout") &&
    !agentLayoutSource.includes("useEffect"),
  "Widths below 1536px must start collapsed without later overriding the user's choice.",
);
assert(
  workspaceViewSource.includes(
    "const shouldDockAgent = !state.agent.isPanelCollapsed",
  ) &&
    workspaceViewSource.includes("<ResumeDetailAgentToggle") &&
    workspaceViewSource.includes("toolbarTrailing={") &&
    workspaceViewSource.includes(
      'minmax(0,1fr) var(--agent-panel-width)',
    ) &&
    /@media \(min-width: 1280px\) \{[\s\S]{0,2400}\.resume-workspace\s*\{[\s\S]{0,400}grid-template-columns:\s*var\(\s*--resume-workspace-columns/.test(
      appStylesSource,
    ),
  "Desktop layouts must compose the editor, canvas, and inline Agent as three tracks with the toggle inside the canvas toolbar.",
);
assert(
  appStylesSource.includes(
    "grid-template-columns: minmax(0, 1fr);",
  ) &&
    appStylesSource.includes(
      ".resume-workspace > .agent-panel-dock {\n    grid-column: 1;\n    grid-row: 2;",
    ) &&
    appStylesSource.includes(
      ".resume-workspace > .resume-preview-card {\n    grid-column: 1;\n    grid-row: 2;",
    ) &&
    appStylesSource.includes(
      '.resume-workspace[data-agent-expanded="true"] > .resume-preview-card {\n    grid-row: 3;',
    ),
  "Sub-1280 layouts must use one column and place the expanded Agent before the preview.",
);
assert(
  !panelSource.includes("data-mode="),
  "A single Agent presentation must not retain a mode discriminator.",
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

{
  const sessionRequest = createDeferred();
  const activeRunRequest = createDeferred();
  const messageWrites = [];
  const reconciledDrafts = [];
  const loadErrorWrites = [];
  let cleanup = () => undefined;
  const runtime = {
    activeRequestAbort: null,
    activeRun: null,
    onReconcileAgentDraft: (draft) => reconciledDrafts.push(draft),
    optimisticMessageOwner: null,
    previewedEditsKey: null,
    sessionReady: true,
    sessionReadyPromise: null,
    sessionRevision: "existing-revision",
    stopRequested: false,
  };
  const authoritativeSession = {
    executions: [],
    messages: [
      {
        id: "assistant-authoritative",
        role: "assistant",
        text: "saved",
        response: {
          draft: { baseResume: {}, status: "pending" },
          edits: [
            {
              id: "edit-authoritative",
              target: "basics.summary",
              title: "Saved edit",
            },
          ],
          id: "assistant-authoritative",
          role: "assistant",
          text: "saved",
          transactionState: "committed",
        },
      },
    ],
    resumeId: "resume-hydration-race",
    revision: "authoritative-revision",
  };
  const messageModel = await loadTypeScriptModule(
    join(copilotRoot, "copilot-message-model.ts"),
    {
      "@/i18n": {
        loadMessages: () =>
          Promise.resolve({ agentTransientModelStatusTexts: [] }),
        locales: ["en"],
      },
      "@/lib/resume": { createId: () => "generated-message" },
    },
  );
  const hydrationModule = await loadTypeScriptModule(
    join(copilotRoot, "use-agent-session-hydration.ts"),
    {
      react: {
        useEffect: (effect) => {
          cleanup = effect();
        },
      },
      "@/lib/agent-session-run-client": {
        loadActiveAgentRun: () => activeRunRequest.promise,
        loadAgentSession: () => sessionRequest.promise,
      },
      "@/lib/agent-stream-client": {
        connectAgentRun: () => {
          throw new Error("The stream must not start after bootstrap failure.");
        },
      },
      "@/lib/api-client": {
        isAbortError: () => false,
      },
      "./copilot-message-model": messageModel,
    },
    {
      console: { error: () => undefined },
    },
  );

  hydrationModule.useAgentSessionHydration({
    cancelScheduledSend: () => false,
    consumeRunStream: () => {
      throw new Error("The stream must not start after bootstrap failure.");
    },
    resumeId: "resume-hydration-race",
    retryAttempt: 0,
    runtimeRef: { current: runtime },
    updates: {
      setIsResponding: () => undefined,
      setMessages: (value) => messageWrites.push(value),
      setSessionLoadError: (value) => loadErrorWrites.push(value),
      setSessionReady: () => undefined,
      setStreamingMessage: () => undefined,
    },
  });

  sessionRequest.resolve(authoritativeSession);
  await flushAsyncWork();
  const committedWhileRunPending = messageWrites.some(
    (value) => Array.isArray(value) && value[0]?.id === "assistant-authoritative",
  );
  const reconciledWhileRunPending = reconciledDrafts.length > 0;
  const revisionWhileRunPending = runtime.sessionRevision;

  activeRunRequest.reject(new Error("active run lookup failed"));
  await flushAsyncWork();

  assert(
    !committedWhileRunPending &&
      !reconciledWhileRunPending &&
      revisionWhileRunPending === null,
    "Session history and its formal draft preview must not commit while the active-run read is pending.",
  );
  assert(
    !messageWrites.some(
      (value) => Array.isArray(value) && value[0]?.id === "assistant-authoritative",
    ) &&
      reconciledDrafts.length === 0 &&
      runtime.sessionRevision === null &&
      loadErrorWrites.at(-1) === true,
    "A failed active-run read must leave session history, revision, and the formal draft preview uncommitted.",
  );

  cleanup();
}

console.log("Agent panel race checks passed.");
