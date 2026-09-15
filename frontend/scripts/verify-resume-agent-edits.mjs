import { readdir, readFile } from "node:fs/promises";
import ts from "typescript";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
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
        ts.isImportDeclaration(statement) || ts.isExportDeclaration(statement)
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

const agentEditModuleUrls = [
  new URL("../src/lib/resume-agent-edits.ts", import.meta.url),
  new URL("../src/lib/resume-agent-edits/transaction-core.ts", import.meta.url),
  new URL("../src/lib/resume-agent-edits/apply-operations.ts", import.meta.url),
  new URL("../src/lib/resume-agent-edits/three-way-merge.ts", import.meta.url),
];
const [sessionSource, draftHookSource, agentEditModuleSources, moduleEntries] =
  await Promise.all([
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
    Promise.all(
      agentEditModuleUrls.map((moduleUrl) => readFile(moduleUrl, "utf8")),
    ),
    readdir(new URL("../src/lib/resume-agent-edits/", import.meta.url)),
  ]);

assert(
  JSON.stringify(
    moduleEntries.filter((entry) => entry.endsWith(".ts")).sort(),
  ) ===
    JSON.stringify([
      "apply-operations.ts",
      "three-way-merge.ts",
      "transaction-core.ts",
    ]),
  "Resume Agent edits must keep one focused implementation module per transaction responsibility.",
);

const agentEditModulePaths = new Set(
  agentEditModuleUrls.map((moduleUrl) => moduleUrl.pathname),
);
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
  !/useResumeAgentDraft|agentDraftBaseRef|createAgentDraftBaseSnapshot|applyAgentEditsWithMerge|agentDraft|previewResume|useDeferredValue/.test(
    sessionSource,
  ),
  "Formal resume sessions must not own Agent draft projections or transactions.",
);
assert(
  !/createContext|useContext|useEffect/.test(draftHookSource),
  "The workspace-owned Agent draft hook must not introduce Context or effect-synchronized input state.",
);

console.log("Resume agent edit architecture checks passed.");
