import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const componentsRoot = path.join(frontendRoot, "src", "components");
const modules = [
  "agent-settings-tab.tsx",
  "deleted-resume-trash-list.tsx",
  "deleted-template-trash-list.tsx",
  "password-settings-dialog.tsx",
  "recycle-bin-delete-dialog.tsx",
  "recycle-bin-format.ts",
  "recycle-bin-panel.tsx",
  "recycle-bin-preview-dialog.tsx",
  "recycle-bin-table.tsx",
  "recycle-bin-types.ts",
  "settings-controls.tsx",
  "settings-panel-types.ts",
  "settings-panel.tsx",
  "site-settings-tab.tsx",
  "username-settings-dialog.tsx",
  "use-password-settings.ts",
  "use-recycle-bin-actions.ts",
  "use-recycle-bin-controller.ts",
  "use-recycle-bin-selection.ts",
  "use-username-settings.ts",
];

function resolvePanelImport(moduleName, specifier) {
  let resolved;

  if (specifier.startsWith("@/components/")) {
    resolved = specifier.slice("@/components/".length);
  } else if (specifier.startsWith(".")) {
    resolved = path.posix.normalize(
      path.posix.join(path.posix.dirname(moduleName), specifier),
    );
  } else {
    return null;
  }

  for (const suffix of ["", ".ts", ".tsx"]) {
    const candidate = `${resolved}${suffix}`;
    if (modules.includes(candidate)) {
      return candidate;
    }
  }
  return null;
}

function collectDependencies(sourceFile, moduleName) {
  const dependencies = new Set();

  for (const statement of sourceFile.statements) {
    assert.equal(
      ts.isExportDeclaration(statement),
      false,
      `${moduleName} must not become a barrel or compatibility facade.`,
    );
    if (!ts.isImportDeclaration(statement)) {
      continue;
    }

    const dependency = resolvePanelImport(
      moduleName,
      statement.moduleSpecifier.text,
    );
    if (dependency) {
      dependencies.add(dependency);
    }
  }

  return dependencies;
}

function assertAcyclic(graph) {
  const visiting = new Set();
  const visited = new Set();

  function visit(moduleName, trail) {
    if (visiting.has(moduleName)) {
      throw new Error(
        `Settings/trash view modules must remain acyclic: ${[
          ...trail,
          moduleName,
        ].join(" -> ")}`,
      );
    }
    if (visited.has(moduleName)) {
      return;
    }

    visiting.add(moduleName);
    for (const dependency of graph.get(moduleName) ?? []) {
      visit(dependency, [...trail, moduleName]);
    }
    visiting.delete(moduleName);
    visited.add(moduleName);
  }

  for (const moduleName of graph.keys()) {
    visit(moduleName, []);
  }
}

const graph = new Map();
const sources = new Map();

for (const moduleName of modules) {
  const source = await readFile(path.join(componentsRoot, moduleName), "utf8");
  const sourceFile = ts.createSourceFile(
    moduleName,
    source,
    ts.ScriptTarget.Latest,
    true,
    moduleName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  assert.equal(
    callNames(sourceFile).some(
      (name) => name === "createContext" || name === "useContext",
    ),
    false,
    `${moduleName} must keep explicit local controller seams instead of broad context.`,
  );
  graph.set(moduleName, collectDependencies(sourceFile, moduleName));
  sources.set(moduleName, sourceFile);
}

function callNames(sourceFile) {
  const names = [];
  function visit(node) {
    if (ts.isCallExpression(node)) {
      if (ts.isIdentifier(node.expression)) names.push(node.expression.text);
      else if (ts.isPropertyAccessExpression(node.expression))
        names.push(node.expression.name.text);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return names;
}
assertAcyclic(graph);
for (const [module, dependencies] of [
  ["settings-panel.tsx", ["site-settings-tab.tsx", "agent-settings-tab.tsx"]],
  [
    "site-settings-tab.tsx",
    [
      "use-password-settings.ts",
      "password-settings-dialog.tsx",
      "username-settings-dialog.tsx",
    ],
  ],
  [
    "recycle-bin-panel.tsx",
    [
      "use-recycle-bin-controller.ts",
      "deleted-resume-trash-list.tsx",
      "deleted-template-trash-list.tsx",
      "recycle-bin-delete-dialog.tsx",
      "recycle-bin-preview-dialog.tsx",
    ],
  ],
  [
    "use-recycle-bin-controller.ts",
    ["use-recycle-bin-actions.ts", "use-recycle-bin-selection.ts"],
  ],
  ["deleted-resume-trash-list.tsx", ["recycle-bin-table.tsx"]],
  ["deleted-template-trash-list.tsx", ["recycle-bin-table.tsx"]],
]) {
  for (const dependency of dependencies)
    assert.ok(
      graph.get(module).has(dependency),
      `${module} must retain its ${dependency} boundary.`,
    );
}
for (const [module, forbidden] of [
  [
    "settings-panel.tsx",
    ["useState", "updateAuthPassword", "ModelProviderIcon"],
  ],
  [
    "recycle-bin-panel.tsx",
    ["useState", "useEffect", "useSearchParams", "ResumeThumbnail"],
  ],
  ["deleted-resume-trash-list.tsx", ["ViewTransitionBoundary"]],
  ["deleted-template-trash-list.tsx", ["ViewTransitionBoundary"]],
]) {
  const source = sources.get(module);
  function visit(node) {
    if (ts.isIdentifier(node))
      assert.ok(
        !forbidden.includes(node.text),
        `${module} must keep ${node.text} behind its controller/view boundary.`,
      );
    ts.forEachChild(node, visit);
  }
  visit(source);
}
for (const statement of sources.get("recycle-bin-table.tsx").statements) {
  if (ts.isFunctionDeclaration(statement))
    assert.ok(
      !["TrashItemRow", "TrashSelectionToolbar"].includes(statement.name?.text),
      "The recycle bin must not expose obsolete row/selection facades.",
    );
}
let hasLazyPreview = false;
function visitPreview(node) {
  if (
    ts.isCallExpression(node) &&
    ts.isIdentifier(node.expression) &&
    node.expression.text === "lazy" &&
    node.arguments.some(
      (argument) =>
        ts.isIdentifier(argument) && argument.text === "loadDocumentCanvas",
    )
  )
    hasLazyPreview = true;
  ts.forEachChild(node, visitPreview);
}
visitPreview(sources.get("recycle-bin-preview-dialog.tsx"));
assert.ok(
  hasLazyPreview,
  "The recycle-bin preview must keep its canvas behind the shared lazy loader.",
);
console.log("Settings and recycle-bin dependency boundaries verified.");
