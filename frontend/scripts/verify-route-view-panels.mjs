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
  "recycle-bin-item-row.tsx",
  "recycle-bin-panel.tsx",
  "recycle-bin-types.ts",
  "settings-controls.tsx",
  "settings-panel-types.ts",
  "settings-panel.tsx",
  "site-settings-tab.tsx",
  "use-password-settings.ts",
  "use-recycle-bin-actions.ts",
  "use-recycle-bin-controller.ts",
  "use-recycle-bin-selection.ts",
];

function countLines(source) {
  const lines = source.split(/\r\n|\n|\r/).length;
  return /(?:\r\n|\n|\r)$/.test(source) ? lines - 1 : lines;
}

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
  const limit = moduleName.endsWith(".tsx") ? 500 : 600;

  assert.ok(
    countLines(source) <= limit,
    `${moduleName} must stay within the default ${limit}-line source budget.`,
  );
  assert.doesNotMatch(
    source,
    /\b(?:createContext|useContext)\s*\(/,
    `${moduleName} must keep explicit local controller seams instead of broad context.`,
  );
  graph.set(moduleName, collectDependencies(sourceFile, moduleName));
  sources.set(moduleName, source);
}

assertAcyclic(graph);

const settingsPanel = sources.get("settings-panel.tsx");
const siteSettings = sources.get("site-settings-tab.tsx");
const agentSettings = sources.get("agent-settings-tab.tsx");
const passwordSettings = sources.get("password-settings-dialog.tsx");
const passwordController = sources.get("use-password-settings.ts");
const recyclePanel = sources.get("recycle-bin-panel.tsx");
const recycleActions = sources.get("use-recycle-bin-actions.ts");
const recycleSelection = sources.get("use-recycle-bin-selection.ts");
const recycleController = sources.get("use-recycle-bin-controller.ts");
const recycleRows = sources.get("recycle-bin-item-row.tsx");
const resumeTrash = sources.get("deleted-resume-trash-list.tsx");
const templateTrash = sources.get("deleted-template-trash-list.tsx");
const deleteDialog = sources.get("recycle-bin-delete-dialog.tsx");

assert.match(settingsPanel, /useSearchParams\(\)/);
assert.match(settingsPanel, /<SiteSettingsTab/);
assert.match(settingsPanel, /<AgentSettingsTab/);
assert.doesNotMatch(
  settingsPanel,
  /\b(?:useState|updateAuthPassword|ModelProviderIcon)\b/,
  "SettingsPanel must remain URL-tab orchestration rather than owning tab state machines.",
);
assert.match(siteSettings, /onLocaleChange\(value\)/);
assert.match(siteSettings, /onThemeChange/);
assert.match(siteSettings, /<PasswordSettingsDialog/);
assert.match(siteSettings, /usePasswordSettings\(/);
assert.match(agentSettings, /defaultModelId: value/);
assert.match(agentSettings, /responseLanguage: value/);
assert.match(agentSettings, /behaviorMode: value/);
assert.match(agentSettings, /confirmationMode: value/);
assert.match(passwordSettings, /controller\.changeCurrentPassword/);
assert.match(passwordController, /validatePasswordUpdateForm\(/);
assert.match(passwordController, /await updateAuthPassword\(/);
assert.match(passwordController, /onPasswordChanged\(\)/);

assert.match(recyclePanel, /useRecycleBinController\(props\)/);
assert.match(recyclePanel, /<DeletedResumeTrashList/);
assert.match(recyclePanel, /<DeletedTemplateTrashList/);
assert.match(recyclePanel, /<RecycleBinDeleteDialog/);
assert.doesNotMatch(
  recyclePanel,
  /\b(?:useState|useEffect|useSearchParams|ResumeThumbnail)\b/,
  "RecycleBinPanel must remain narrow view/controller orchestration.",
);
assert.match(recycleActions, /runningActionRef/);
assert.match(recycleActions, /finally\s*{/);
assert.match(recycleActions, /onDeleteResumeForever\(action\.ids\)/);
assert.match(recycleActions, /onDeleteTemplateForever\(action\.ids\)/);
assert.match(recycleSelection, /const TRASH_PAGE_SIZE = 10/);
assert.match(recycleSelection, /useSearchParams\(\)/);
assert.match(recycleSelection, /\{ replace: true \}/);
assert.match(recycleSelection, /page === safeCurrentPage/);
assert.match(recycleController, /useRecycleBinActions\(/);
assert.match(recycleController, /useRecycleBinSelection\(/);
assert.match(recycleController, /selection\.removeResumeIds/);
assert.match(recycleController, /selection\.removeTemplateIds/);
assert.match(recycleRows, /preview\/resume-thumbnail/);
assert.match(recycleRows, /aria-hidden="true"/);
assert.match(recycleRows, /pointer-events-none/);
assert.match(resumeTrash, /<ViewTransitionBoundary/);
assert.match(resumeTrash, /<GalleryPagination/);
assert.match(templateTrash, /<ViewTransitionBoundary/);
assert.match(templateTrash, /showEmptyTemplateImagePlaceholders/);
assert.match(deleteDialog, /<ConfirmActionDialog/);
assert.match(deleteDialog, /deferClose/);
assert.match(deleteDialog, /!isRunning\(\)/);

console.log("Settings and recycle-bin controller/view boundaries verified.");
