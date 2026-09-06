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

const [enMessages, zhMessages] = await Promise.all([
  readFile(
    path.join(frontendRoot, "src", "i18n", "locales", "en.json"),
    "utf8",
  ).then(JSON.parse),
  readFile(
    path.join(frontendRoot, "src", "i18n", "locales", "zh.json"),
    "utf8",
  ).then(JSON.parse),
]);

assertAcyclic(graph);

const settingsPanel = sources.get("settings-panel.tsx");
const settingsControls = sources.get("settings-controls.tsx");
const settingsRow = settingsControls.slice(
  settingsControls.indexOf("export function SettingsRow"),
  settingsControls.indexOf("export function SettingsSection"),
);
const settingsSection = settingsControls.slice(
  settingsControls.indexOf("export function SettingsSection"),
  settingsControls.indexOf("export function OptionToggleGroup"),
);
const siteSettings = sources.get("site-settings-tab.tsx");
const agentSettings = sources.get("agent-settings-tab.tsx");
const preferencesSettingsSection = siteSettings.slice(
  siteSettings.indexOf("<SettingsSection title={t.preferencesSettingsTitle}>"),
  siteSettings.indexOf(
    "<SettingsSection title={t.accountSecuritySettingsTitle}>",
  ),
);
const securitySettingsSection = siteSettings.slice(
  siteSettings.indexOf(
    "<SettingsSection title={t.accountSecuritySettingsTitle}>",
  ),
  siteSettings.indexOf("</TabsContent>"),
);
const passwordSettings = sources.get("password-settings-dialog.tsx");
const passwordController = sources.get("use-password-settings.ts");
const recyclePanel = sources.get("recycle-bin-panel.tsx");
const recycleActions = sources.get("use-recycle-bin-actions.ts");
const recycleSelection = sources.get("use-recycle-bin-selection.ts");
const recycleController = sources.get("use-recycle-bin-controller.ts");
const recyclePreviewDialog = sources.get("recycle-bin-preview-dialog.tsx");
const recycleTable = sources.get("recycle-bin-table.tsx");
const resumeTrash = sources.get("deleted-resume-trash-list.tsx");
const templateTrash = sources.get("deleted-template-trash-list.tsx");
const deleteDialog = sources.get("recycle-bin-delete-dialog.tsx");
const trashCountBadge = recycleTable.slice(
  recycleTable.indexOf("export function TrashCountBadge"),
  recycleTable.indexOf("export function RecycleBinThumbnail"),
);
const recycleDeletedAtColumn = recycleTable.slice(
  recycleTable.indexOf('id: "deletedAt"'),
  recycleTable.indexOf('id: "actions"'),
);

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
assert.match(
  settingsRow,
  /\bmin-h-20\b[\s\S]*\bpy-4\b/,
  "Settings rows must retain their comfortable mobile height and padding.",
);
assert.match(
  settingsRow,
  /\bsm:min-h-16\b[\s\S]*\bsm:py-3\b/,
  "Settings rows must use the approved compact desktop density.",
);
assert.doesNotMatch(
  settingsSection,
  /\bicon\b/,
  "Settings section headings must stay text-only so row and choice icons retain a clear hierarchy.",
);
assert.match(
  settingsSection,
  /<section\b[\s\S]*<h2\b[\s\S]*<Card\b/,
  "Settings section headings must sit outside their cards as semantic headings.",
);
assert.doesNotMatch(
  settingsSection,
  /\bCard(?:Header|Title)\b/,
  "Grouped settings cards must not restore an internal title band.",
);
assert.equal(
  (siteSettings.match(/<SettingsSection\b/g) ?? []).length,
  2,
  "General settings must group language and theme as preferences while keeping account security separate.",
);
assert.match(siteSettings, /title=\{t\.preferencesSettingsTitle\}/);
assert.equal(
  (preferencesSettingsSection.match(/<SettingsRow\b/g) ?? []).length,
  2,
  "The preferences card must contain language and theme rows.",
);
assert.equal(
  (preferencesSettingsSection.match(/<Separator\b/g) ?? []).length,
  1,
  "The preferences card must separate its language and theme rows.",
);
assert.equal(
  (securitySettingsSection.match(/<SettingsRow\b/g) ?? []).length,
  1,
  "Account security must remain a focused single-row card.",
);
assert.match(securitySettingsSection, /<PasswordSettingsDialog\b/);
assert.equal(
  (agentSettings.match(/<SettingsSection\b/g) ?? []).length,
  2,
  "Agent settings must keep model and interaction preferences as separate sections.",
);
assert.match(
  settingsControls,
  /text-muted-foreground transition-colors duration-150/,
  "Settings option groups must keep inactive choices visually secondary and animate only color changes.",
);
assert.doesNotMatch(
  settingsControls,
  /data-\[state=on\]:(?:bg|text)-primary/,
  "Settings option groups must not resemble primary actions or navigation tabs.",
);
assert.match(agentSettings, /defaultModelConfigId: value/);
assert.match(agentSettings, /responseLanguage: value/);
assert.match(agentSettings, /behaviorMode: value/);
assert.match(agentSettings, /confirmationMode: value/);
const settingsSelectSources = `${siteSettings}\n${agentSettings}`;
assert.equal(
  (siteSettings.match(/className="ml-auto w-28 max-w-full"/g) ?? []).length,
  1,
  "The general language Select must stay compact without overflowing.",
);
assert.equal(
  (agentSettings.match(/className="ml-auto w-full sm:max-w-64"/g) ?? [])
    .length,
  1,
  "The default-model Select must retain room for longer values.",
);
assert.equal(
  (agentSettings.match(/className="ml-auto w-40"/g) ?? []).length,
  1,
  "The response-language Select must balance compactness and label length.",
);
for (const [attribute, pattern] of [
  ["align", /align="end"/g],
  ["position", /position="popper"/g],
  ["side offset", /sideOffset=\{4\}/g],
]) {
  assert.equal(
    (settingsSelectSources.match(pattern) ?? []).length,
    3,
    `Settings Select content must consistently use its ${attribute} contract.`,
  );
}
assert.doesNotMatch(
  agentSettings,
  /<SelectContent\s+className="min-w-\[20rem\]"/,
  "The default-model Select content must inherit the trigger width.",
);
assert.match(passwordSettings, /controller\.changeCurrentPassword/);
assert.match(passwordController, /validatePasswordUpdateForm\(/);
assert.match(passwordController, /await updateAuthPassword\(/);
assert.match(passwordController, /onPasswordChanged\(\)/);

assert.match(recyclePanel, /useRecycleBinController\(props\)/);
assert.match(recyclePanel, /<DeletedResumeTrashList/);
assert.match(recyclePanel, /<DeletedTemplateTrashList/);
assert.match(recyclePanel, /<RecycleBinDeleteDialog/);
assert.match(
  recyclePanel,
  /<section[\s\S]{0,160}className="[^"]*bg-muted\/35[^"]*"/,
  "Recycle-bin workspace surface must match the resume and template galleries.",
);
assert.equal(
  (recyclePanel.match(/group\/trash-tab/g) ?? []).length,
  2,
  "Both recycle-bin tabs must expose their active state to the count badge.",
);
assert.match(trashCountBadge, /variant="secondary"/);
assert.match(
  trashCountBadge,
  /group-data-\[state=inactive\]\/trash-tab:bg-background/,
  "Inactive recycle-bin counts must contrast with the muted tab list.",
);
assert.doesNotMatch(
  recyclePanel,
  /\b(?:useState|useEffect|useSearchParams|ResumeThumbnail)\b/,
  "RecycleBinPanel must remain narrow view/controller orchestration.",
);
assert.match(recycleActions, /runningActionRef/);
assert.match(recycleActions, /finally\s*{/);
assert.match(recycleActions, /onDeleteResumeForever\(action\.ids\)/);
assert.match(recycleActions, /onDeleteTemplateForever\(action\.ids\)/);
assert.match(recycleSelection, /const TRASH_PAGE_SIZE = 6/);
assert.match(recycleSelection, /useSearchParams\(\)/);
assert.match(recycleSelection, /\{ replace: true \}/);
assert.match(recycleSelection, /page === safeCurrentPage/);
assert.match(recycleController, /useRecycleBinActions\(/);
assert.match(recycleController, /useRecycleBinSelection\(/);
assert.match(recycleController, /selection\.removeResumeIds/);
assert.match(recycleController, /selection\.removeTemplateIds/);
assert.match(recycleController, /openPreview/);
assert.match(recycleController, /previewTriggerRef/);
assert.match(recycleTable, /from "@\/components\/data-table"/);
assert.match(recycleTable, /ColumnDef<RecycleBinTableItem>/);
assert.match(recycleTable, /getRowId=\{\(item\) => item\.id\}/);
assert.match(recycleTable, /toggleAllPageRowsSelected\(checked === true\)/);
assert.match(recycleTable, /row\.toggleSelected\(checked === true\)/);
assert.match(recycleTable, /preview\/resume-thumbnail/);
assert.equal(
  (recycleDeletedAtColumn.match(/\btext-center\b/g) ?? []).length,
  2,
  "The recycle-bin deleted-at header and values must share centered alignment.",
);
assert.match(recycleTable, /aria-hidden="true"/);
assert.match(recycleTable, /pointer-events-none/);
assert.match(recycleTable, /const canBulkAction = selectedCount > 0/);
assert.match(recycleTable, /data-slot="trash-bulk-actions"/);
assert.match(recycleTable, /aria-hidden=\{!canBulkAction\}/);
assert.match(recycleTable, /inert=\{!canBulkAction\}/);
assert.match(
  recycleTable,
  /<DropdownMenu[\s\S]*?<DropdownMenuGroup>[\s\S]*?onPreview\(item\.previewTarget[\s\S]*?onRestore\(item\.id\)[\s\S]*?<\/DropdownMenuGroup>[\s\S]*?<DropdownMenuSeparator \/>[\s\S]*?<DropdownMenuGroup>[\s\S]*?variant="destructive"[\s\S]*?onDelete\(item\.id\)/,
  "Recycle-bin table rows must group preview with restore and isolate destructive delete.",
);
assert.match(
  recycleTable,
  /<DropdownMenuContent[\s\S]{0,120}className="w-32 whitespace-nowrap"/,
  "Recycle-bin row menus must use the compact width while keeping localized actions on one line.",
);
assert.match(resumeTrash, /deleteLabel=\{t\.deleteTrashItemAction\}/);
assert.match(templateTrash, /deleteLabel=\{t\.deleteTrashItemAction\}/);
assert.match(deleteDialog, /:\s*t\.deleteForever/);
assert.equal(enMessages.deleteTrashItemAction, "Delete");
assert.equal(zhMessages.deleteTrashItemAction, "删除");
assert.match(
  recyclePreviewDialog,
  /<DialogTitle[\s\S]*?className="sr-only"[\s\S]*?tabIndex=\{-1\}/,
  "The long recycle preview must use its static title as the initial focus target.",
);
assert.match(recyclePreviewDialog, /<DialogDescription className="sr-only">/);
assert.match(recyclePreviewDialog, /closeLabel=\{t\.close\}/);
assert.match(recyclePreviewDialog, /onOpenAutoFocus=/);
assert.match(recyclePreviewDialog, /lazy\(loadDocumentCanvas\)/);
assert.match(recyclePreviewDialog, /data-slot="trash-preview-dialog"/);
assert.match(
  recyclePreviewDialog,
  /<DialogContent[\s\S]*?rounded-\(--radius-preview\)/,
  "The dialog clip must use the same radius as the visible preview card.",
);
assert.doesNotMatch(
  recyclePreviewDialog,
  /showPreviewTitle/,
  "The recycle preview must not retain the removed visual preview title option.",
);
assert.match(
  recyclePreviewDialog,
  /<DialogContent[\s\S]*?\bborder-0\b[\s\S]*?\bbg-transparent\b[\s\S]*?\bshadow-none\b/,
  "The recycle preview dialog must let the preview card be the only visible surface.",
);
assert.doesNotMatch(
  recyclePreviewDialog,
  /<DialogHeader|bg-muted\/35|mx-auto max-w-4xl/,
  "The recycle preview dialog must not restore a visible title band or padded outer shell.",
);
assert.match(recyclePreviewDialog, /variant="template"[\s\S]*?template=\{target\.template\}/);
assert.match(recyclePreviewDialog, /variant="resume"[\s\S]*?typography=\{target\.typography\}/);
assert.doesNotMatch(
  recycleTable,
  /export function (?:TrashItemRow|TrashSelectionToolbar)/,
  "The recycle bin must not retain its former div-row or duplicate select-all toolbar.",
);
assert.match(recyclePanel, /<TrashBulkActions/);
assert.match(recyclePanel, /<RecycleBinPreviewDialog/);
assert.doesNotMatch(resumeTrash, /ViewTransitionBoundary/);
assert.match(resumeTrash, /<GalleryPagination/);
assert.match(resumeTrash, /<RecycleBinTable/);
assert.match(resumeTrash, /previewTarget:/);
assert.match(
  resumeTrash,
  /createTemplateSettings\(baseTemplate\.preset,[\s\S]*?item\.templateSettings/,
  "Deleted resume previews must retain their resume-level template settings.",
);
assert.doesNotMatch(resumeTrash, /<TrashItemRow|<TrashSelectionToolbar/);
assert.match(
  resumeTrash,
  /data-slot="trash-list-content"[\s\S]{0,100}className="min-h-\[390px\] overflow-hidden"/,
  "The resume trash list must preserve the same low-data baseline as its empty state.",
);
assert.doesNotMatch(templateTrash, /ViewTransitionBoundary/);
assert.match(templateTrash, /showEmptyTemplateImagePlaceholders/);
assert.match(templateTrash, /<RecycleBinTable/);
assert.match(templateTrash, /previewTarget:/);
assert.doesNotMatch(templateTrash, /<TrashItemRow|<TrashSelectionToolbar/);
assert.match(
  templateTrash,
  /data-slot="trash-list-content"[\s\S]{0,100}className="min-h-\[390px\] overflow-hidden"/,
  "The template trash list must preserve the same low-data baseline as its empty state.",
);
assert.match(deleteDialog, /<ConfirmActionDialog/);
assert.match(deleteDialog, /deferClose/);
assert.match(deleteDialog, /!isRunning\(\)/);

console.log("Settings and recycle-bin controller/view boundaries verified.");
