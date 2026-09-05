import { readdir, readFile } from "node:fs/promises";
import { createServer } from "vite";
import ts from "typescript";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function countLines(source) {
  if (source.length === 0) {
    return 0;
  }

  const lines = source.split(/\r\n|\n|\r/).length;
  return /(?:\r\n|\n|\r)$/.test(source) ? lines - 1 : lines;
}

function collectModuleDependencies(moduleUrl, source, modulePaths) {
  const dependencies = [];
  const sourceFile = ts.createSourceFile(
    moduleUrl.pathname,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  );

  for (const statement of sourceFile.statements) {
    if (
      !(
        ts.isImportDeclaration(statement) ||
        ts.isExportDeclaration(statement)
      ) ||
      !statement.moduleSpecifier ||
      !ts.isStringLiteralLike(statement.moduleSpecifier)
    ) {
      continue;
    }

    const specifier = statement.moduleSpecifier.text;
    if (!specifier.startsWith(".")) {
      continue;
    }

    const resolvedPath = new URL(
      specifier.endsWith(".ts") ? specifier : `${specifier}.ts`,
      moduleUrl,
    ).pathname;
    if (modulePaths.has(resolvedPath)) {
      dependencies.push(resolvedPath);
    }
  }

  return dependencies;
}

function assertAcyclicModuleGraph(graph) {
  const visiting = new Set();
  const visited = new Set();

  function visit(modulePath) {
    assert(
      !visiting.has(modulePath),
      `Resume Agent edit modules must remain acyclic; cycle includes ${modulePath}.`,
    );
    if (visited.has(modulePath)) {
      return;
    }

    visiting.add(modulePath);
    for (const dependency of graph.get(modulePath) ?? []) {
      visit(dependency);
    }
    visiting.delete(modulePath);
    visited.add(modulePath);
  }

  for (const modulePath of graph.keys()) {
    visit(modulePath);
  }
}

function createResume() {
  return {
    schemaVersion: 2,
    basic: {
      name: "Original name",
      headline: "Engineer",
      phone: "",
      email: "",
      location: "",
      avatar: "",
      summary: "Original summary",
      customFields: [],
    },
    sections: [
      {
        id: "education",
        kind: "education",
        title: "Education",
        items: [],
      },
    ],
  };
}

function createAppliedResume() {
  const resume = createResume();
  resume.basic.headline = "Staff Engineer";
  return resume;
}

function createDraftSession(status, revision) {
  const baseResume = createResume();
  return {
    resumeId: "resume-draft-decision",
    revision,
    executions: [],
    messages: [
      {
        id: "assistant-draft-decision",
        role: "assistant",
        text: "The edit is ready.",
        createdAt: "2026-08-09T12:00:00.000Z",
        response: {
          id: "assistant-draft-decision",
          role: "assistant",
          text: "The edit is ready.",
          edits: [
            {
              id: "edit-draft-decision",
              title: "Update headline",
              target: "basic.headline",
              reason: "Use the requested title.",
              operation: {
                type: "replace_field",
                path: "basic.headline",
                value: "Staff Engineer",
              },
            },
          ],
          transactionState: "committed",
          draft: {
            baseResume,
            reviewItems: [
              {
                id: "agent-review-edit-draft-decision",
                editIds: ["edit-draft-decision"],
                status,
              },
            ],
          },
        },
      },
    ],
  };
}

function createResumeDetail(
  versionId = "version-formal",
  resumeData = createResume(),
) {
  return {
    resume: {
      id: "resume-draft-decision",
      title: "Draft decision resume",
      updatedAt: "2026-08-09T12:00:00.000Z",
      jobBrief: "",
      typography: { fontFamily: "inter", fontSize: 16 },
      template: "minimal",
      templateSettings: null,
      resume: resumeData,
    },
    savedAt: "2026-08-09T12:00:00.000Z",
    versionId,
  };
}

function apiResponse(data, status = 200) {
  return new Response(
    JSON.stringify({ code: 0, data, message: "SUCCESS" }),
    {
      headers: { "Content-Type": "application/json" },
      status,
    },
  );
}

function transportError(code, details = {}) {
  return new Response(
    JSON.stringify({ detail: { code, ...details } }),
    {
      headers: { "Content-Type": "application/json" },
      status: 409,
    },
  );
}

const agentEditModuleUrls = [
  new URL("../src/lib/resume-agent-edits.ts", import.meta.url),
  new URL("../src/lib/resume-agent-edits/transaction-core.ts", import.meta.url),
  new URL("../src/lib/resume-agent-edits/apply-operations.ts", import.meta.url),
  new URL("../src/lib/resume-agent-edits/three-way-merge.ts", import.meta.url),
];
const [
  sessionSource,
  draftHookSource,
  reviewSelectionSource,
  hydrationSource,
  conversationSource,
  saveSource,
  workspaceSource,
  agentEditModuleSources,
  moduleEntries,
] = await Promise.all([
  readFile(
    new URL(
      "../src/components/workspace/use-resume-detail-session.ts",
      import.meta.url,
    ),
    "utf8",
  ),
  readFile(
    new URL("../src/hooks/use-resume-agent-draft.ts", import.meta.url),
    "utf8",
  ),
  readFile(
    new URL(
      "../src/hooks/use-agent-draft-review-selection.ts",
      import.meta.url,
    ),
    "utf8",
  ),
  readFile(
    new URL(
      "../src/components/copilot/use-agent-session-hydration.ts",
      import.meta.url,
    ),
    "utf8",
  ),
  readFile(
    new URL(
      "../src/components/copilot/use-agent-conversation.ts",
      import.meta.url,
    ),
    "utf8",
  ),
  readFile(
    new URL(
      "../src/components/workspace/use-resume-detail-save.ts",
      import.meta.url,
    ),
    "utf8",
  ),
  readFile(
    new URL(
      "../src/components/workspace/use-resume-detail-workspace.ts",
      import.meta.url,
    ),
    "utf8",
  ),
  Promise.all(agentEditModuleUrls.map((moduleUrl) => readFile(moduleUrl, "utf8"))),
  readdir(new URL("../src/lib/resume-agent-edits/", import.meta.url)),
]);

assert(
  JSON.stringify(moduleEntries.filter((entry) => entry.endsWith(".ts")).sort()) ===
    JSON.stringify([
      "apply-operations.ts",
      "three-way-merge.ts",
      "transaction-core.ts",
    ]),
  "Resume Agent edits must keep one focused implementation module per transaction responsibility.",
);
agentEditModuleSources.forEach((source, index) => {
  assert(
    countLines(source) <= 600,
    `${agentEditModuleUrls[index].pathname} must stay within the 600-line TypeScript budget.`,
  );
});

const agentEditModulePaths = new Set(agentEditModuleUrls.map((moduleUrl) => moduleUrl.pathname));
const agentEditGraph = new Map(
  agentEditModuleUrls.map((moduleUrl, index) => [
    moduleUrl.pathname,
    collectModuleDependencies(
      moduleUrl,
      agentEditModuleSources[index],
      agentEditModulePaths,
    ),
  ]),
);
assertAcyclicModuleGraph(agentEditGraph);

const [entryPath, transactionCorePath, operationApplyPath, mergePath] =
  agentEditModuleUrls.map((moduleUrl) => moduleUrl.pathname);
const expectedAgentEditGraph = new Map([
  [entryPath, [operationApplyPath, mergePath, transactionCorePath]],
  [transactionCorePath, []],
  [operationApplyPath, [transactionCorePath]],
  [mergePath, [operationApplyPath, transactionCorePath]],
]);
for (const [modulePath, expectedDependencies] of expectedAgentEditGraph) {
  assert(
    JSON.stringify([...(agentEditGraph.get(modulePath) ?? [])].sort()) ===
      JSON.stringify([...expectedDependencies].sort()),
    `${modulePath} must preserve the one-way Resume Agent edit dependency graph.`,
  );
}

const [agentEditEntrySource, transactionCoreSource] = agentEditModuleSources;
assert(
  /export type \{\s*AgentDraftApplyError,\s*AgentDraftApplyErrorReason,\s*AgentDraftApplyResult,?\s*\}/.test(
    agentEditEntrySource,
  ) &&
    !/export\s+(?:type\s+)?\*\s+from/.test(agentEditEntrySource) &&
    !/^export\s+(?:async\s+)?function\s+(?!createAgentDraftBaseSnapshot|applyAgentEditsToDraft|applyAgentEditsWithMerge)/m.test(
      agentEditEntrySource,
    ),
  "The Resume Agent edit entry must expose only the three product APIs and their result types.",
);
assert(
  !/createAgentDraftBaseSnapshot|applyAgentEditsToDraft|applyAgentEditsWithMerge/.test(
    transactionCoreSource,
  ),
  "Product orchestration must remain in the public entry instead of becoming a shallow facade.",
);

assert(
    /import\s*\{\s*useResumeAgentDraft\s*\}\s*from\s*["']@\/hooks\/use-resume-agent-draft["']/.test(
    sessionSource,
  ) &&
    /useResumeAgentDraft\(\{[\s\S]*?messages,[\s\S]*?onApplyResume:\s*applyAgentDraftResume[\s\S]*?resume,[\s\S]*?\}\)/.test(
      sessionSource,
    ) &&
    !/agentDraftBaseRef|currentResumeRef|createAgentDraftBaseSnapshot|applyAgentEditsWithMerge/.test(
      sessionSource,
    ),
  "The resume detail session must consume the Agent draft transaction through one hook seam.",
);
assert(
  !/createContext|useContext/.test(draftHookSource) &&
    !/useEffect/.test(draftHookSource) &&
    /const currentResumeRef = useRef\(resume\);/.test(
      draftHookSource,
    ) &&
    /currentResumeRef\.current = resume;/.test(
      draftHookSource,
    ) &&
    /projectAgentDraftReview\(\{[\s\S]*?baseResume:[\s\S]*?currentResume: currentResumeRef\.current/.test(
      draftHookSource,
    ),
  "The Agent draft hook must read the latest editor resume without introducing Context.",
);
assert(
  /existingCreatedAt:\s*currentDraft\?\.id === draftId\s*\? currentDraft\.createdAt\s*: undefined/.test(
    draftHookSource,
  ),
  "Replacement batches from one Agent message must retain their original creation time.",
);
assert(
  /if \(result\.errors\.length > 0\) \{\s*if \(transactionState === "committed"\) \{[\s\S]*?clearRejectedAgentDraft\(sourceMessageId\)[\s\S]*?toast\.error/.test(
    draftHookSource,
  ) &&
    /if \(reviewItems\.length === 0\) \{\s*if \(transactionState === "committed"\) \{\s*clearRejectedAgentDraft\(sourceMessageId\)/.test(
      draftHookSource,
    ),
  "Only a committed Agent batch may clear and report a rejected provisional draft.",
);
assert(
  /const resolveCurrentScope = useCallback\([\s\S]*?draft\.transactionState !== "committed"/.test(
    draftHookSource,
  ) &&
    /selection\.mode === "single"[\s\S]*?\[selectedItem\][\s\S]*?: previousPendingItems/.test(
      draftHookSource,
    ),
  "Apply and discard must stay committed-only and resolve the visible review scope.",
);
assert(
  /onResolveDraftReview\(\s*draft\.sourceMessageId,\s*currentResumeRef\.current,\s*reviewItemIds,\s*status,?\s*\)/.test(
      draftHookSource,
    ) &&
    /status === "applied"[\s\S]*?currentResume,[\s\S]*?currentVersionId:[\s\S]*?rebaseOnLatest:[\s\S]*?reviewItemIds,[\s\S]*?status,[\s\S]*?: \{ reviewItemIds, status \}/.test(
      saveSource,
    ),
  "Each draft decision must persist the exact review-item scope and current editor state.",
);
assert(
  /selection\.beginDecisionExit\(reviewItemIds\)[\s\S]*?setResolvingStatus\(status\)[\s\S]*?Promise\.all\(\[[\s\S]*?decisionRequest,[\s\S]*?waitForAgentDraftReviewExit\(\)/.test(
    draftHookSource,
  ) &&
    /setResolvingStatus\(null\)[\s\S]*?endDecisionExit\(\)/.test(
      draftHookSource,
    ) &&
    /getAgentDraftReviewSuccessorId\([\s\S]*?previousPendingItems[\s\S]*?remainingPendingItems/.test(
      draftHookSource,
    ),
  "A decision must expose exit animation state and advance single-item review after persistence.",
);
assert(
  /current\.mode === "all"[\s\S]*?filter\(\(item\) => item\.id !== reviewItemId\)[\s\S]*?: current\.reviewItemId[\s\S]*?\[current\.reviewItemId\]/.test(
    reviewSelectionSource,
  ) &&
    /exitingIds\.length === 0 \|\| prefersReducedMotion\(\)[\s\S]*?commitSelection\(next\)/.test(
      reviewSelectionSource,
    ) &&
    /window\.setTimeout\([\s\S]*?REVIEW_SELECTION_EXIT_MS/.test(
      reviewSelectionSource,
    ) &&
    /prefers-reduced-motion: reduce/.test(reviewSelectionSource),
  "All-to-single and single-to-single navigation must animate disappearing regions and switch immediately for reduced motion.",
);
assert(
  /agentDraftState:\s*agentDraft[,\n]/.test(draftHookSource) &&
    !/lastAgentDraft/.test(draftHookSource),
  "Only a draft with pending review items may be carried into the next Agent request.",
);
assert(
  /const resolveAgentDraftReview = useCallback\([\s\S]*?while \(activeRequestRef\.current\)[\s\S]*?resolveAgentDraftDecision\([\s\S]*?adoptPersistedSave\([\s\S]*?activeRequestRef\.current = trackedRequest/.test(
    saveSource,
  ) &&
    /const resolveAgentDraftReviewRef = useRef[\s\S]*?onResolveDraftReview:\s*resolveAgentDraftReview[\s\S]*?resolveAgentDraftReviewRef\.current = save\.resolveAgentDraftReview/.test(
      workspaceSource,
    ) &&
    /onResolveDraftReview,[\s\S]*?useResumeAgentDraft\(\{[\s\S]*?onResolveDraftReview/.test(
      sessionSource,
    ),
  "Draft review decisions must serialize with resume saves and adopt only authoritative receipts.",
);
assert(
  /const canAdoptFormalResume =\s*!hasLocalChanges \|\|\s*\(status === "applied" &&\s*resolution\.committed &&\s*resolution\.resolvedAsRequested\)/.test(
    saveSource,
  ),
  "Unsaved local edits may adopt a formal resume only after this apply was committed as requested.",
);
assert(
  (sessionSource.match(/resetAgentDraft\(\)/g) ?? []).length === 1 &&
    /const resetAgentDraft = useCallback\(\(\) => \{[\s\S]*?agentDraftBaseRef\.current\s*=\s*null[\s\S]*?setStoredAgentDraft\(null\)[\s\S]*?setResolvingStatus\(null\)[\s\S]*?reviewSelectionControllerRef\.current\?\.reset\(\)/.test(
      draftHookSource,
    ),
  "Hydrating a resume detail session must reset the complete Agent draft transaction.",
);
assert(
  /const \{ draftSnapshot, panelMessages, session \}\s*=\s*await hydrateAgentSession/.test(
    hydrationSource,
  ) &&
    /runtime\.onReconcileAgentDraft\(draftSnapshot\)/.test(
      hydrationSource,
    ) &&
    /const \{ draftSnapshot, panelMessages, session \} = await hydrateAgentSession[\s\S]*?runtime\.onReconcileAgentDraft\(draftSnapshot\)/.test(
      conversationSource,
    ),
  "Every authoritative session load must reconcile a pending, terminal, or absent draft.",
);

const server = await createServer({
  cacheDir: createViteTestCacheDir(),
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  root: process.cwd(),
  server: { hmr: false, middlewareMode: true, ws: false },
  resolve: {
    alias: { "@": new URL("../src", import.meta.url).pathname },
  },
});

try {
const agentEditModule = await server.ssrLoadModule(
  "/src/lib/resume-agent-edits.ts",
);
const {
  createProvisionalAgentDraftReviewItems,
  createReviewItemIdByOperationId,
  getAdjacentAgentDraftReviewItemId,
  getAgentDraftReviewSuccessorId,
  getPendingAgentDraftReviewItems,
  projectAgentDraftReview,
} = await server.ssrLoadModule("/src/lib/agent-draft-review.ts");
const {
  getAgentDraftSnapshot,
  getPendingAgentDraftSnapshot,
  hydrateAgentSession,
  toConversationMessage,
} = await server.ssrLoadModule(
  "/src/components/copilot/copilot-message-model.ts",
);
assert(
  JSON.stringify(Object.keys(agentEditModule).sort()) ===
    JSON.stringify([
      "applyAgentEditsToDraft",
      "applyAgentEditsWithMerge",
      "createAgentDraftBaseSnapshot",
    ]),
  "The Resume Agent edit runtime entry must expose exactly the three product APIs.",
);
const {
  applyAgentEditsToDraft,
  applyAgentEditsWithMerge,
  createAgentDraftBaseSnapshot,
} = agentEditModule;

{
  const baseResume = createResume();
  const edits = [
    {
      id: "review-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Use the requested role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Frontend Engineer",
      },
    },
    {
      id: "review-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Focus the introduction.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Frontend-focused summary",
      },
    },
  ];
  const reviewItems = createProvisionalAgentDraftReviewItems(edits);
  const allProjection = projectAgentDraftReview({
    baseResume,
    currentResume: baseResume,
    edits,
    reviewItems,
  });
  const singleProjection = projectAgentDraftReview({
    baseResume,
    currentResume: baseResume,
    edits,
    reviewItemIds: [reviewItems[0].id],
    reviewItems,
  });

  assert(
    allProjection.resume.basic.headline === "Frontend Engineer" &&
      allProjection.resume.basic.summary === "Frontend-focused summary" &&
      allProjection.diffs.length === 2,
    "All-mode review must render every pending review item.",
  );
  assert(
    singleProjection.resume.basic.headline === "Frontend Engineer" &&
      singleProjection.resume.basic.summary === "Original summary" &&
      singleProjection.diffs.length === 1,
    "Single-mode review must remove every other pending proposal from the rendered resume.",
  );
  assert(
    createReviewItemIdByOperationId(reviewItems)["review-summary"] ===
      reviewItems[1].id &&
      getAdjacentAgentDraftReviewItemId(reviewItems, null, 1) ===
        reviewItems[0].id &&
      getAdjacentAgentDraftReviewItemId(
        reviewItems,
        reviewItems[0].id,
        -1,
      ) === reviewItems[1].id,
    "Review navigation and operation mapping must use stable review-item ids.",
  );

  const resolvedItems = structuredClone(reviewItems);
  resolvedItems[0].status = "applied";
  const remainingItems = getPendingAgentDraftReviewItems(resolvedItems);
  assert(
    remainingItems.length === 1 &&
      getAgentDraftReviewSuccessorId(
        reviewItems,
        remainingItems,
        reviewItems[0].id,
      ) === reviewItems[1].id,
    "Resolving one item must decrement the pending count and select its successor.",
  );
}

{
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.headline = "User-edited headline";
  const edits = [
    {
      id: "partial-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the introduction.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
    {
      id: "partial-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the target role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Agent-edited headline",
      },
    },
  ];
  const reviewItems = createProvisionalAgentDraftReviewItems(edits);
  const appliedSummary = projectAgentDraftReview({
    baseResume,
    currentResume,
    edits,
    reviewItemIds: [reviewItems[0].id],
    reviewItems,
  });
  const remainingReviewItems = structuredClone(reviewItems);
  remainingReviewItems[0].status = "applied";
  const headlineAfterSummaryApply = projectAgentDraftReview({
    baseResume,
    currentResume: appliedSummary.resume,
    edits,
    reviewItemIds: [remainingReviewItems[1].id],
    reviewItems: remainingReviewItems,
  });

  assert(
    appliedSummary.errors.length === 0 &&
      appliedSummary.resume.basic.summary === "Agent-edited summary" &&
      appliedSummary.resume.basic.headline === "User-edited headline",
    "Applying one review item must preserve a disjoint local edit in the formal candidate.",
  );
  assert(
    headlineAfterSummaryApply.errors.length === 1 &&
      headlineAfterSummaryApply.errors[0].reason === "conflict" &&
      headlineAfterSummaryApply.resume.basic.headline === "User-edited headline",
    "A later review item must still compare with the immutable draft base and reject a competing local edit.",
  );
}

{
  const baseResume = createResume();
  const edit = {
    id: "durable-edit",
    title: "Update headline",
    target: "basic.headline",
    reason: "Use the requested title.",
    operation: {
      type: "replace_field",
      path: "basic.headline",
      value: "Staff Engineer",
    },
    status: "executed",
    diffs: [{
      id: "diff-durable-edit",
      operationId: "durable-edit",
      path: "basic.headline",
      kind: "modified",
      label: "Headline",
      before: "Engineer",
      after: "Staff Engineer",
    }],
  };
  const storedMessages = [
    {
      id: "assistant-durable-draft",
      role: "assistant",
      text: "The edit is ready.",
      createdAt: "2026-08-09T12:00:00.000Z",
      response: {
        id: "assistant-durable-draft",
        role: "assistant",
        text: "The edit is ready.",
        edits: [edit],
        transactionState: "committed",
          draft: {
            baseResume,
            reviewItems: [
              {
                id: "agent-review-durable-edit",
                editIds: ["durable-edit"],
                status: "pending",
              },
            ],
          },
      },
    },
  ];
  const pendingDraft = getPendingAgentDraftSnapshot(storedMessages);

  assert(
    pendingDraft?.sourceMessageId === "assistant-durable-draft" &&
      pendingDraft.transactionState === "committed" &&
      pendingDraft.baseResume === baseResume &&
      pendingDraft.edits[0] === edit,
    "Session hydration must recover the committed pending draft and its immutable base.",
  );
  const terminalMessages = structuredClone(storedMessages);
  terminalMessages[0].response.draft.reviewItems[0].status = "discarded";
  assert(
    getAgentDraftSnapshot(terminalMessages)?.reviewItems[0].status ===
      "discarded" &&
      getAgentDraftSnapshot([]) === null,
    "Authoritative hydration must distinguish a terminal draft from no draft.",
  );

  const hydrated = await hydrateAgentSession(
    Promise.resolve({
      resumeId: "resume-durable-draft",
      revision: "revision-durable-draft",
      messages: storedMessages,
      executions: [],
    }),
  );
  assert(
    hydrated.draftSnapshot?.sourceMessageId === "assistant-durable-draft" &&
      hydrated.draftSnapshot.baseResume === baseResume &&
      hydrated.draftSnapshot.reviewItems[0].status === "pending",
    "The session hydration interface must return the pending draft alongside panel history.",
  );

  const replacementMessage = toConversationMessage(
    hydrated.panelMessages[0],
  );
  assert(
    replacementMessage.response?.draft?.reviewItems[0].status === "pending" &&
      replacementMessage.response.draft.baseResume === baseResume &&
      replacementMessage.response.edits?.[0]?.diffs?.[0]?.operationId ===
        "durable-edit",
    "History replacement must preserve the durable draft payload on retained assistant messages.",
  );
}

{
  const storedResponse = {
    id: "assistant-complete-history",
    role: "assistant",
    tone: "success",
    text: "I checked the source and completed the analysis.",
    reasoning: "Concise retained reasoning",
    updates: ["Transient provider status"],
    timeline: [
      {
        id: "timeline-tool-group",
        type: "tool_group",
        toolIds: ["tool-success", "tool-error"],
      },
    ],
    plan: ["Inspect evidence"],
    suggestions: ["Tighten the summary"],
    knowledge: [{ title: "Requirement", detail: "TypeScript" }],
    tools: [
      {
        id: "tool-success",
        type: "tool-web_fetch",
        title: "web_fetch",
        state: "output-available",
        input: { url: "https://example.com/job" },
        output: {
          sourceId: "source-public-job",
          url: "https://example.com/job",
        },
        startedAt: "2026-08-10T10:00:00.000Z",
        completedAt: "2026-08-10T10:00:01.000Z",
      },
      {
        id: "tool-error",
        type: "tool-web_fetch",
        title: "web_fetch",
        state: "output-error",
        input: { url: "https://example.com/job" },
        errorText: "Fetch failed",
        startedAt: "2026-08-10T10:00:02.000Z",
        completedAt: "2026-08-10T10:00:03.000Z",
      },
    ],
    sources: [
      {
        id: "source-public-job",
        title: "Public job description",
        sourceType: "web",
        url: "https://example.com/job",
        excerpt: "Build accessible React and TypeScript products.",
      },
    ],
    transactionState: "none",
  };
  const hydrated = await hydrateAgentSession(
    Promise.resolve({
      resumeId: "resume-complete-history",
      revision: "revision-complete-history",
      messages: [
        {
          id: storedResponse.id,
          role: "assistant",
          text: storedResponse.text,
          createdAt: "2026-08-10T10:00:04.000Z",
          response: storedResponse,
        },
      ],
      executions: [],
    }),
  );
  const sanitizedResponse = hydrated.panelMessages[0].response;
  const replacementResponse = toConversationMessage(
    hydrated.panelMessages[0],
  ).response;

  assert(
    JSON.stringify(replacementResponse) === JSON.stringify(sanitizedResponse) &&
      replacementResponse.sources.length === 1 &&
      replacementResponse.sources[0].excerpt ===
        "Build accessible React and TypeScript products." &&
      replacementResponse.tools[0].input.url === "https://example.com/job" &&
      replacementResponse.tools[0].output.sourceId === "source-public-job" &&
      replacementResponse.tools[1].errorText === "Fetch failed" &&
      replacementResponse.tools[1].completedAt ===
        "2026-08-10T10:00:03.000Z",
    "History replacement must preserve the complete sanitized assistant response for PUT-to-GET equivalence.",
  );
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "experience",
    kind: "experience",
    title: "Experience",
    items: ["first", "second", "third", "fourth"].map((id) => ({
      id,
      company: id,
      position: "",
      location: "",
      period: "",
      description: "",
      highlights: [],
    })),
  });
  const result = applyAgentEditsToDraft(baseResume, [{
    id: "reorder-items-precisely",
    title: "Reorder experience",
    target: "sections.experience.items",
    reason: "Verify each changed object.",
    operation: {
      type: "reorder_items",
      sectionId: "experience",
      itemIds: ["second", "fourth", "first", "third"],
    },
  }]);

  assert(
    JSON.stringify(result.diffs.map((diff) => ({
      path: diff.path,
      itemId: diff.itemId,
      before: diff.before,
      after: diff.after,
    }))) === JSON.stringify([
      { path: "sections.experience.items.first", itemId: "first", before: 0, after: 2 },
      { path: "sections.experience.items.third", itemId: "third", before: 2, after: 3 },
    ]),
    "An item reorder must mark the deterministic minimal moved set from the longest common subsequence.",
  );
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "experience",
    kind: "experience",
    title: "Experience",
    items: [
      { id: "first", company: "First", position: "", location: "", period: "", description: "", highlights: [] },
      { id: "second", company: "Second", position: "", location: "", period: "", description: "", highlights: [] },
    ],
  });
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "delete-second-item",
      title: "Delete second item",
      target: "sections.experience.items.second",
      reason: "Verify the exact review boundary.",
      operation: {
        type: "delete_item",
        sectionId: "experience",
        itemId: "second",
      },
    },
    {
      id: "delete-education-section",
      title: "Delete education",
      target: "sections.education",
      reason: "Verify the exact review boundary.",
      operation: {
        type: "delete_section",
        sectionId: "education",
      },
    },
  ]);

  assert(
    result.diffs[0]?.beforePreviousId === "first" &&
      result.diffs[0]?.beforeNextId === undefined &&
      result.diffs[1]?.beforePreviousId === undefined &&
      result.diffs[1]?.beforeNextId === "experience",
    "Structural deletion diffs must retain stable pre-deletion neighbors.",
  );
}

{
  const baseResume = createResume();
  baseResume.sections.push(
    {
      id: "experience",
      kind: "experience",
      title: "Experience",
      items: [],
    },
    {
      id: "projects",
      kind: "project",
      title: "Projects",
      items: [],
    },
  );
  const result = applyAgentEditsToDraft(baseResume, [{
    id: "reorder-sections-precisely",
    title: "Reorder sections",
    target: "sections",
    reason: "Verify each changed object.",
    operation: {
      type: "reorder_sections",
      sectionIds: ["experience", "projects", "education"],
    },
  }]);

  assert(
    JSON.stringify(result.diffs.map((diff) => ({
      path: diff.path,
      sectionId: diff.sectionId,
      before: diff.before,
      after: diff.after,
    }))) === JSON.stringify([
      { path: "sections.education", sectionId: "education", before: 0, after: 2 },
    ]),
    "Moving the first section to the end must mark only that section as moved.",
  );
}

{
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the candidate's role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
    {
      id: "delete-missing-section",
      title: "Delete missing section",
      target: "sections.missing",
      reason: "Exercise transaction rollback.",
      operation: {
        type: "delete_section",
        sectionId: "missing",
      },
    },
  ]);

  assert(
    result.appliedCount === 0,
    "A batch containing any failed edit must report zero applied edits.",
  );
  assert(
    result.diffs.length === 0,
    "A rejected batch must not expose partial diffs.",
  );
  assert(
    JSON.stringify(result.resume) === JSON.stringify(baseResume),
    "A rejected batch must return the original resume state.",
  );
  assert(
    result.errors.length === 1 &&
      result.errors[0].editId === "delete-missing-section" &&
      result.errors[0].reason === "target_not_found" &&
      result.errors[0].target === "sections.missing",
    "A rejected batch must return a structured, actionable error.",
  );
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "skills",
    kind: "simple_list",
    title: "Skills",
    items: [
      {
        id: "skill-1",
        content: "React, TypeScript",
      },
    ],
  });
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-invalid-skills",
      title: "Add skill highlights",
      target: "sections.skills.items.skill-1",
      reason: "Exercise list-item update validation.",
      operation: {
        type: "update_item",
        sectionId: "skills",
        itemId: "skill-1",
        patch: { highlights: ["React"] },
      },
    },
  ]);

  assert(
    result.appliedCount === 0 &&
      result.errors.length === 1 &&
      result.errors[0].reason === "invalid_operation" &&
      result.resume.sections[1].items[0].content === "React, TypeScript",
    "Simple-list updates must reject fields outside the content contract.",
  );
}

for (const operation of [
  {
    type: "insert_item",
    sectionId: "skills",
    item: { id: "skill-2", content: "TypeScript" },
  },
  {
    type: "delete_item",
    sectionId: "skills",
    itemId: "skill-1",
  },
  {
    type: "reorder_items",
    sectionId: "skills",
    itemIds: ["skill-1"],
  },
]) {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "skills",
    kind: "simple_list",
    title: "Skills",
    items: [{ id: "skill-1", content: "<ul><li>React</li></ul>" }],
  });
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: `reject-${operation.type}`,
      title: "Keep the single rich-text item",
      target: "sections.skills.items",
      reason: "Exercise the simple-list cardinality contract.",
      operation,
    },
  ]);

  assert(
    result.appliedCount === 0 &&
      result.errors.length === 1 &&
      result.errors[0].reason === "invalid_operation" &&
      JSON.stringify(result.resume) === JSON.stringify(baseResume),
    `Simple-list sections must reject ${operation.type}.`,
  );
}

{
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "insert-invalid-skills",
      title: "Add skills",
      target: "sections.skills",
      reason: "Exercise the canonical list-item contract.",
      operation: {
        type: "insert_section",
        section: {
          id: "skills",
          kind: "simple_list",
          title: "Skills",
          items: [
            {
              id: "skill-1",
              content: "Frontend",
              highlights: ["React"],
            },
          ],
        },
      },
    },
  ]);

  assert(
    result.appliedCount === 0 &&
      result.errors.length === 1 &&
      result.errors[0].reason === "invalid_operation",
    "Simple-list sections must reject fields outside id and content.",
  );
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "experience",
    kind: "experience",
    title: "Experience",
    items: [
      {
        id: "experience-1",
        company: "Example Inc.",
        position: "Engineer",
        location: "Remote",
        period: "2024 - Present",
        description: "",
        highlights: [],
      },
    ],
  });
  baseResume.sections.push({
    id: "skills",
    kind: "simple_list",
    title: "Skills",
    items: [{ id: "skill-1", content: "React" }],
  });

  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-position",
      title: "Clarify the experience",
      target: "sections.experience.items.experience-1",
      reason: "Use the semantic experience fields.",
      operation: {
        type: "update_item",
        sectionId: "experience",
        itemId: "experience-1",
        patch: {
          position: "Senior Engineer",
          description: "Built the editor platform.",
          highlights: ["Reduced state complexity."],
        },
      },
    },
    {
      id: "update-skills",
      title: "Add a skill",
      target: "sections.skills.items.skill-1.content",
      reason: "A simple-list item remains a directly editable string.",
      operation: {
        type: "update_item",
        sectionId: "skills",
        itemId: "skill-1",
        patch: { content: "React · TypeScript" },
      },
    },
  ]);

  assert(
    result.errors.length === 0 && result.appliedCount === 2,
    "Valid semantic item fields must be applied atomically.",
  );
  assert(
    result.resume.sections[1].items[0].position === "Senior Engineer" &&
      result.resume.sections[1].items[0].company === "Example Inc." &&
      result.resume.sections[2].items[0].content === "React · TypeScript",
    "Agent item edits must preserve unrelated fields and support simple-list strings.",
  );
  assert(
    result.diffs.length === 4,
    "One multi-field edit must expose one precise diff per changed field without changing applied edit count.",
  );
  assert(
    JSON.stringify(result.diffs.map((diff) => diff.path)) ===
      JSON.stringify([
        "sections.experience.items.experience-1.position",
        "sections.experience.items.experience-1.description",
        "sections.experience.items.experience-1.highlights",
        "sections.skills.items.skill-1.content",
      ]),
    "Item diffs must use canonical field paths instead of a whole-item target.",
  );
  assert(
    JSON.stringify(result.diffs[0]) ===
      JSON.stringify({
        id: "diff-update-position-position",
        operationId: "update-position",
        path: "sections.experience.items.experience-1.position",
        kind: "modified",
        label: "Clarify the experience",
        sectionId: "experience",
        itemId: "experience-1",
        before: "Engineer",
        after: "Senior Engineer",
      }),
    "A field diff must carry only that field's before and after values.",
  );
}

{
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the candidate's role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Updated summary",
      },
    },
  ]);

  assert(result.errors.length === 0, "A valid batch must not return errors.");
  assert(result.appliedCount === 2, "A valid batch must commit every edit.");
  assert(result.diffs.length === 2, "A valid batch must expose every diff.");
  assert(
    result.resume.basic.headline === "Staff Engineer" &&
      result.resume.basic.summary === "Updated summary",
    "A valid batch must return the fully updated resume.",
  );
  assert(
    baseResume.basic.headline === "Engineer" &&
      baseResume.basic.summary === "Original summary",
    "Applying a batch must never mutate the source resume.",
  );
}

{
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "reject-location",
      title: "Reject hidden location",
      target: "basic.location",
      reason: "Location is outside the Agent write contract.",
      operation: {
        type: "replace_field",
        path: "basic.location",
        value: "Remote",
      },
    },
  ]);

  assert(
    result.errors.length === 1 && result.appliedCount === 0,
    "Agent drafts must reject hidden basic fields on the frontend boundary.",
  );
  assert(
    result.resume.basic.location === "",
    "A rejected location edit must not change the resume.",
  );
}

{
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the candidate's role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
    {
      id: "unknown-operation",
      title: "Run unsupported operation",
      target: "sections.education",
      reason: "Exercise runtime payload validation.",
      operation: {
        type: "operation_from_a_newer_server",
      },
    },
  ]);

  assert(
    result.appliedCount === 0 && result.resume.basic.headline === "Engineer",
    "An unknown operation must reject and roll back the entire batch.",
  );
  assert(
    result.errors.length === 1 &&
      result.errors[0].editId === "unknown-operation" &&
      result.errors[0].reason === "invalid_operation",
    "An unknown operation must produce a structured validation error.",
  );
}

{
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.name = "User-edited name";
  const result = applyAgentEditsWithMerge(baseResume, currentResume, [
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
  ]);

  assert(result.errors.length === 0, "Disjoint field edits must merge.");
  assert(
    result.resume.basic.name === "User-edited name" &&
      result.resume.basic.summary === "Agent-edited summary",
    "A merge must preserve the user's concurrent field edit.",
  );
}

{
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.summary = "User-edited summary";
  const result = applyAgentEditsWithMerge(baseResume, currentResume, [
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
  ]);

  assert(
    result.errors.length === 1 && result.errors[0].reason === "conflict",
    "Competing edits to the same field must reject the candidate.",
  );
  assert(
    result.resume.basic.summary === "User-edited summary",
    "A conflict must leave the current resume untouched.",
  );
}

{
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.name = "User-edited name";
  const result = applyAgentEditsWithMerge(baseResume, currentResume, [
    {
      id: "insert-projects",
      title: "Add projects",
      target: "sections.projects",
      reason: "Add project evidence.",
      operation: {
        type: "insert_section",
        index: 1,
        section: {
          id: "projects",
          kind: "project",
          title: "Projects",
          items: [],
        },
      },
    },
  ]);

  assert(result.errors.length === 0, "A unique structural insert must merge.");
  assert(
    result.resume.basic.name === "User-edited name" &&
      result.resume.sections[1]?.id === "projects",
    "A structural insert must retain unrelated user field edits.",
  );
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "projects",
    kind: "project",
    title: "Projects",
    items: [],
  });
  const currentResume = structuredClone(baseResume);
  currentResume.sections.push({
    id: "skills",
    kind: "simple_list",
    title: "Skills",
    items: [{ id: "skill-1", content: "<ul><li>React</li></ul>" }],
  });
  const result = applyAgentEditsWithMerge(baseResume, currentResume, [
    {
      id: "reorder-sections",
      title: "Prioritize projects",
      target: "sections",
      reason: "Lead with project evidence.",
      operation: {
        type: "reorder_sections",
        sectionIds: ["projects", "education"],
      },
    },
  ]);

  assert(
    result.errors.length === 1 && result.errors[0].reason === "conflict",
    "Concurrent structural changes must reject the candidate.",
  );
  assert(
    result.resume.sections.map((section) => section.id).join("|") ===
      "education|projects|skills",
    "A structural conflict must not reorder the current resume.",
  );
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "projects",
    kind: "project",
    title: "Projects",
    items: [],
  });
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "partial-reorder",
      title: "Partially reorder sections",
      target: "sections",
      reason: "Exercise complete-order validation.",
      operation: {
        type: "reorder_sections",
        sectionIds: ["projects"],
      },
    },
  ]);

  assert(
    result.errors.length === 1 &&
      result.errors[0].reason === "invalid_operation",
    "A reorder must include every current section exactly once.",
  );
}

{
  const baseResume = createResume();
  const draftBase = createAgentDraftBaseSnapshot(baseResume);
  const edits = [
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
  ];
  const generatedDraft = applyAgentEditsWithMerge(
    draftBase,
    baseResume,
    edits,
  );
  const latestResume = structuredClone(baseResume);
  latestResume.basic.name = "User edit after draft generation";
  const appliedDraft = applyAgentEditsWithMerge(
    draftBase,
    latestResume,
    edits,
  );

  assert(
    generatedDraft.resume.basic.summary === "Agent-edited summary",
    "Draft generation must still preview the Agent batch.",
  );
  assert(
    appliedDraft.errors.length === 0 &&
      appliedDraft.resume.basic.name ===
        "User edit after draft generation" &&
      appliedDraft.resume.basic.summary === "Agent-edited summary",
    "Applying a stored draft must rebase onto manual edits made after draft generation.",
  );
}

{
  const originalResume = createResume();
  const transactionBase = createAgentDraftBaseSnapshot(originalResume);
  const firstDraftEdits = [
    {
      id: "initial-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Create the first pending draft.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
  ];
  const firstDraft = applyAgentEditsWithMerge(
    transactionBase,
    originalResume,
    firstDraftEdits,
  );
  const followUpEdits = [
    {
      id: "refined-headline",
      title: "Refine headline",
      target: "basic.headline",
      reason: "Continue from the pending Staff Engineer candidate.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Principal Engineer",
      },
    },
    {
      id: "follow-up-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Apply a disjoint follow-up edit.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Focused summary",
      },
    },
  ];
  const refinedDraft = applyAgentEditsWithMerge(
    transactionBase,
    originalResume,
    [...firstDraftEdits, ...followUpEdits],
  );

  assert(
    firstDraft.errors.length === 0 &&
      firstDraft.resume.basic.headline === "Staff Engineer",
    "The first pending draft must be a valid candidate built from the immutable base.",
  );
  assert(
    refinedDraft.errors.length === 0 &&
      refinedDraft.resume.basic.headline === "Principal Engineer" &&
      refinedDraft.resume.basic.summary === "Focused summary",
    "A follow-up must replace the same field without conflict and preserve every prior edit.",
  );
}

{
  const baseResume = createResume();
  const draftBase = createAgentDraftBaseSnapshot(baseResume);
  const edits = [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the candidate's role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Agent-edited headline",
      },
    },
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
  ];
  const latestResume = structuredClone(baseResume);
  latestResume.basic.summary = "User edit after draft generation";
  const appliedDraft = applyAgentEditsWithMerge(
    draftBase,
    latestResume,
    edits,
  );

  assert(
    appliedDraft.errors.length === 1 &&
      appliedDraft.errors[0].reason === "conflict",
    "A competing manual edit made after draft generation must reject the draft.",
  );
  assert(
    appliedDraft.appliedCount === 0 &&
      appliedDraft.resume.basic.headline === "Engineer" &&
      appliedDraft.resume.basic.summary ===
        "User edit after draft generation",
    "A late conflict must leave the complete current resume untouched.",
  );
}

{
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const authSession = JSON.stringify({
    accessToken: "agent-draft-token",
    authenticatedAt: new Date().toISOString(),
    expiresAt: "2099-01-01T00:00:00.000Z",
    username: "agent-draft-test",
  });
  const requests = [];
  const responses = [
    apiResponse(createDraftSession("pending", "revision-discard-pending")),
    apiResponse(createResumeDetail("version-discard-formal")),
    apiResponse({
      session: createDraftSession("discarded", "revision-discarded"),
      resume: null,
    }),
  ];

  globalThis.window = {
    location: { assign() {}, pathname: "/resumes/resume-draft-decision" },
    localStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
    sessionStorage: {
      getItem(key) {
        return key === "resumate-auth-session" ? authSession : null;
      },
      removeItem() {},
      setItem() {},
    },
  };
  globalThis.fetch = async (url, options = {}) => {
    requests.push({
      body: options.body,
      method: options.method ?? "GET",
      url: String(url),
    });
    const response = responses.shift();
    assert(response, "The draft discard client made an unexpected request.");
    return response;
  };

  try {
    const { resolveAgentDraftDecision } = await server.ssrLoadModule(
      "/src/lib/agent-session-run-client.ts",
    );
    const resolution = await resolveAgentDraftDecision(
      "resume-draft-decision",
      "assistant-draft-decision",
      {
        reviewItemIds: ["agent-review-edit-draft-decision"],
        status: "discarded",
      },
    );

    assert(
      resolution.draft?.reviewItems[0].status === "discarded" &&
        resolution.resume?.versionId === "version-discard-formal" &&
        resolution.committed &&
        resolution.resolvedAsRequested,
      "A discard must resolve the selected item and retain the fresh formal resume.",
    );
    assert(
      requests.length === 3 &&
        requests[2].method === "PATCH" &&
        requests[2].body ===
          JSON.stringify({
            revision: "revision-discard-pending",
            reviewItemIds: ["agent-review-edit-draft-decision"],
            status: "discarded",
          }),
      "A discard must submit only its review-item scope and session revision.",
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (typeof originalWindow === "undefined") {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

for (const authoritativeStatus of ["applied", "discarded"]) {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const authSession = JSON.stringify({
    accessToken: "agent-draft-token",
    authenticatedAt: new Date().toISOString(),
    expiresAt: "2099-01-01T00:00:00.000Z",
    username: "agent-draft-test",
  });
  const requests = [];
  const responses = [
    apiResponse(createDraftSession(authoritativeStatus, "revision-other-tab")),
    apiResponse(
      createResumeDetail(`version-authoritative-${authoritativeStatus}`),
    ),
  ];

  globalThis.window = {
    location: { assign() {}, pathname: "/resumes/resume-draft-decision" },
    localStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
    sessionStorage: {
      getItem(key) {
        return key === "resumate-auth-session" ? authSession : null;
      },
      removeItem() {},
      setItem() {},
    },
  };
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ method: options.method ?? "GET", url: String(url) });
    const response = responses.shift();
    assert(response, "An authoritative apply read made an unexpected request.");
    return response;
  };

  try {
    const { resolveAgentDraftDecision } = await server.ssrLoadModule(
      "/src/lib/agent-session-run-client.ts",
    );
    const resolution = await resolveAgentDraftDecision(
      "resume-draft-decision",
      "assistant-draft-decision",
      {
        currentResume: createResume(),
        currentVersionId: `version-authoritative-${authoritativeStatus}`,
        rebaseOnLatest: true,
        reviewItemIds: ["agent-review-edit-draft-decision"],
        status: "applied",
      },
    );

    assert(
      resolution.draft?.reviewItems[0].status === authoritativeStatus &&
        resolution.resume?.versionId ===
          `version-authoritative-${authoritativeStatus}` &&
        !resolution.committed &&
        resolution.resolvedAsRequested ===
          (authoritativeStatus === "applied"),
      "An already-processed decision must report whether authority matches the requested status.",
    );
    assert(
      requests.length === 2 && requests.every((request) => request.method === "GET"),
      "An already-processed decision must use authoritative reads without issuing PATCH.",
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (typeof originalWindow === "undefined") {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

{
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const authSession = JSON.stringify({
    accessToken: "agent-draft-token",
    authenticatedAt: new Date().toISOString(),
    expiresAt: "2099-01-01T00:00:00.000Z",
    username: "agent-draft-test",
  });
  const requests = [];
  const responses = [
    apiResponse(createDraftSession("pending", "revision-pending")),
    apiResponse(createResumeDetail()),
    apiResponse({
      session: createDraftSession("applied", "revision-applied"),
      resume: createResumeDetail("version-applied"),
    }),
  ];

  globalThis.window = {
    location: { assign() {}, pathname: "/resumes/resume-draft-decision" },
    localStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
    sessionStorage: {
      getItem(key) {
        return key === "resumate-auth-session" ? authSession : null;
      },
      removeItem() {},
      setItem() {},
    },
  };
  globalThis.fetch = async (url, options = {}) => {
    requests.push({
      body: options.body,
      method: options.method ?? "GET",
      url: String(url),
    });
    const response = responses.shift();
    assert(response, "The draft decision client made an unexpected request.");
    return response;
  };

  try {
    const { resolveAgentDraftDecision } = await server.ssrLoadModule(
      "/src/lib/agent-session-run-client.ts",
    );
    const resolution = await resolveAgentDraftDecision(
      "resume-draft-decision",
      "assistant-draft-decision",
      {
        currentResume: createResume(),
        currentVersionId: "version-formal",
        rebaseOnLatest: false,
        reviewItemIds: ["agent-review-edit-draft-decision"],
        status: "applied",
      },
    );

    assert(
      resolution.draft?.reviewItems[0].status === "applied" &&
        resolution.session.revision === "revision-applied" &&
        resolution.resume?.versionId === "version-applied" &&
        resolution.committed &&
        resolution.resolvedAsRequested,
      "A successful apply must resolve from the durable assistant response.",
    );
    assert(
      requests.length === 3 &&
        requests[0].method === "GET" &&
        requests[1].method === "GET" &&
        requests[2].method === "PATCH" &&
        requests[2].url.endsWith(
          "/api/agent/resumes/resume-draft-decision/session/messages/assistant-draft-decision/draft",
        ) &&
        requests[2].body ===
          JSON.stringify({
            expectedVersionId: "version-formal",
            revision: "revision-pending",
            reviewItemIds: ["agent-review-edit-draft-decision"],
            resume: createAppliedResume(),
            status: "applied",
          }),
      "A draft apply must atomically submit the candidate with both current revisions.",
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (typeof originalWindow === "undefined") {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

{
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const authSession = JSON.stringify({
    accessToken: "agent-draft-token",
    authenticatedAt: new Date().toISOString(),
    expiresAt: "2099-01-01T00:00:00.000Z",
    username: "agent-draft-test",
  });
  const requests = [];
  const responses = [
    apiResponse(createDraftSession("pending", "revision-stale")),
    apiResponse(createResumeDetail()),
    transportError("AGENT_SESSION_REVISION_CONFLICT", {
      revision: "revision-refreshed",
    }),
    apiResponse(createDraftSession("pending", "revision-refreshed")),
    apiResponse(createResumeDetail()),
    apiResponse({
      session: createDraftSession("applied", "revision-reconciled"),
      resume: createResumeDetail("version-reconciled"),
    }),
  ];

  globalThis.window = {
    location: { assign() {}, pathname: "/resumes/resume-draft-decision" },
    localStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
    sessionStorage: {
      getItem(key) {
        return key === "resumate-auth-session" ? authSession : null;
      },
      removeItem() {},
      setItem() {},
    },
  };
  globalThis.fetch = async (url, options = {}) => {
    requests.push({
      body: options.body,
      method: options.method ?? "GET",
      url: String(url),
    });
    const response = responses.shift();
    assert(response, "Draft decision reconciliation exceeded one retry.");
    return response;
  };

  try {
    const { resolveAgentDraftDecision } = await server.ssrLoadModule(
      "/src/lib/agent-session-run-client.ts",
    );
    const resolution = await resolveAgentDraftDecision(
      "resume-draft-decision",
      "assistant-draft-decision",
      {
        currentResume: createResume(),
        currentVersionId: "version-formal",
        rebaseOnLatest: false,
        reviewItemIds: ["agent-review-edit-draft-decision"],
        status: "applied",
      },
    );

    assert(
      resolution.draft?.reviewItems[0].status === "applied" &&
        resolution.session.revision === "revision-reconciled" &&
        resolution.resume?.versionId === "version-reconciled" &&
        resolution.committed &&
        resolution.resolvedAsRequested,
      "A stale draft decision must converge after one authoritative reload.",
    );
    assert(
      requests.length === 6 &&
        requests[2].body ===
          JSON.stringify({
            expectedVersionId: "version-formal",
            revision: "revision-stale",
            reviewItemIds: ["agent-review-edit-draft-decision"],
            resume: createAppliedResume(),
            status: "applied",
          }) &&
        requests[5].body ===
          JSON.stringify({
            expectedVersionId: "version-formal",
            revision: "revision-refreshed",
            reviewItemIds: ["agent-review-edit-draft-decision"],
            resume: createAppliedResume(),
            status: "applied",
          }),
      "A revision conflict may retry once, using the reloaded session and formal resume.",
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (typeof originalWindow === "undefined") {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

{
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const authSession = JSON.stringify({
    accessToken: "agent-draft-token",
    authenticatedAt: new Date().toISOString(),
    expiresAt: "2099-01-01T00:00:00.000Z",
    username: "agent-draft-test",
  });
  const requests = [];
  const responses = [
    apiResponse(createDraftSession("pending", "revision-formal-stale")),
    apiResponse(createResumeDetail("version-stale")),
    transportError("RESUME_VERSION_CONFLICT", {
      versionId: "version-current",
    }),
    apiResponse(
      createDraftSession("pending", "revision-formal-current"),
    ),
    apiResponse(createResumeDetail("version-current")),
  ];

  globalThis.window = {
    location: { assign() {}, pathname: "/resumes/resume-draft-decision" },
    localStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
    sessionStorage: {
      getItem(key) {
        return key === "resumate-auth-session" ? authSession : null;
      },
      removeItem() {},
      setItem() {},
    },
  };
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ method: options.method ?? "GET", url: String(url) });
    const response = responses.shift();
    assert(response, "A formal-version conflict reconciliation made an unexpected request.");
    return response;
  };

  try {
    const { resolveAgentDraftDecision } = await server.ssrLoadModule(
      "/src/lib/agent-session-run-client.ts",
    );
    let conflictRaised = false;
    try {
      await resolveAgentDraftDecision(
        "resume-draft-decision",
        "assistant-draft-decision",
        {
          currentResume: createResume(),
          currentVersionId: "version-stale",
          rebaseOnLatest: false,
          reviewItemIds: ["agent-review-edit-draft-decision"],
          status: "applied",
        },
      );
    } catch {
      conflictRaised = true;
    }

    assert(
      conflictRaised &&
        requests.length === 5 &&
        requests.filter((request) => request.method === "PATCH").length === 1,
      "A stale formal resume with local edits must reload authority, then abort without an overwrite retry.",
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (typeof originalWindow === "undefined") {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

{
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const authSession = JSON.stringify({
    accessToken: "agent-draft-token",
    authenticatedAt: new Date().toISOString(),
    expiresAt: "2099-01-01T00:00:00.000Z",
    username: "agent-draft-test",
  });
  const requests = [];
  const otherTabResume = createResume();
  otherTabResume.basic.summary = "Summary saved by another tab";
  const rebasedResume = createAppliedResume();
  rebasedResume.basic.summary = otherTabResume.basic.summary;
  const responses = [
    apiResponse(createDraftSession("pending", "revision-rebase-stale")),
    apiResponse(createResumeDetail("version-rebase-stale")),
    transportError("RESUME_VERSION_CONFLICT", {
      versionId: "version-rebase-current",
    }),
    apiResponse(createDraftSession("pending", "revision-rebase-current")),
    apiResponse(
      createResumeDetail("version-rebase-current", otherTabResume),
    ),
    apiResponse({
      session: createDraftSession("applied", "revision-rebase-applied"),
      resume: createResumeDetail("version-rebase-applied", rebasedResume),
    }),
  ];

  globalThis.window = {
    location: { assign() {}, pathname: "/resumes/resume-draft-decision" },
    localStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
    sessionStorage: {
      getItem(key) {
        return key === "resumate-auth-session" ? authSession : null;
      },
      removeItem() {},
      setItem() {},
    },
  };
  globalThis.fetch = async (url, options = {}) => {
    requests.push({
      body: options.body,
      method: options.method ?? "GET",
      url: String(url),
    });
    const response = responses.shift();
    assert(response, "A safe draft rebase made an unexpected request.");
    return response;
  };

  try {
    const { resolveAgentDraftDecision } = await server.ssrLoadModule(
      "/src/lib/agent-session-run-client.ts",
    );
    const resolution = await resolveAgentDraftDecision(
      "resume-draft-decision",
      "assistant-draft-decision",
      {
        currentResume: createResume(),
        currentVersionId: "version-rebase-stale",
        rebaseOnLatest: true,
        reviewItemIds: ["agent-review-edit-draft-decision"],
        status: "applied",
      },
    );

    assert(
      resolution.resume?.resume.resume.basic.headline === "Staff Engineer" &&
        resolution.resume.resume.resume.basic.summary ===
          "Summary saved by another tab" &&
        resolution.committed &&
        resolution.resolvedAsRequested,
      "A clean tab must rebase its selected item onto another tab's fresh formal resume.",
    );
    assert(
      requests.length === 6 &&
        requests[5].body ===
          JSON.stringify({
            expectedVersionId: "version-rebase-current",
            revision: "revision-rebase-current",
            reviewItemIds: ["agent-review-edit-draft-decision"],
            resume: rebasedResume,
            status: "applied",
          }),
      "A safe retry must rebuild the candidate from the reloaded formal resume.",
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (typeof originalWindow === "undefined") {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

for (const {
  authoritativeStatus,
  conflictCode,
} of [
  {
    authoritativeStatus: "applied",
    conflictCode: "AGENT_SESSION_REVISION_CONFLICT",
  },
  {
    authoritativeStatus: "discarded",
    conflictCode: "AGENT_DRAFT_DECISION_CONFLICT",
  },
]) {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const authSession = JSON.stringify({
    accessToken: "agent-draft-token",
    authenticatedAt: new Date().toISOString(),
    expiresAt: "2099-01-01T00:00:00.000Z",
    username: "agent-draft-test",
  });
  const requests = [];
  const responses = [
    apiResponse(createDraftSession("pending", "revision-before-terminal")),
    apiResponse(createResumeDetail()),
    transportError(conflictCode, {
      revision: "revision-terminal",
      status: authoritativeStatus,
    }),
    apiResponse(
      createDraftSession(authoritativeStatus, "revision-terminal"),
    ),
    apiResponse(createResumeDetail("version-terminal")),
  ];

  globalThis.window = {
    location: { assign() {}, pathname: "/resumes/resume-draft-decision" },
    localStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
    sessionStorage: {
      getItem(key) {
        return key === "resumate-auth-session" ? authSession : null;
      },
      removeItem() {},
      setItem() {},
    },
  };
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ method: options.method ?? "GET", url: String(url) });
    const response = responses.shift();
    assert(response, "A terminal draft reconciliation must not retry.");
    return response;
  };

  try {
    const { resolveAgentDraftDecision } = await server.ssrLoadModule(
      "/src/lib/agent-session-run-client.ts",
    );
    const resolution = await resolveAgentDraftDecision(
      "resume-draft-decision",
      "assistant-draft-decision",
      {
        currentResume: createResume(),
        currentVersionId: "version-formal",
        rebaseOnLatest: false,
        reviewItemIds: ["agent-review-edit-draft-decision"],
        status: "applied",
      },
    );

    assert(
      resolution.draft?.reviewItems[0].status === authoritativeStatus &&
        requests.length === 5 &&
        !resolution.committed &&
        resolution.resolvedAsRequested ===
          (authoritativeStatus === "applied"),
      "After a 409, the authoritative terminal draft status must win without another PATCH.",
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (typeof originalWindow === "undefined") {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

console.log("Resume agent edit transaction checks passed.");
} finally {
  await server.close();
}
