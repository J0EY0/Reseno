import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const frontendRoot = new URL("../", import.meta.url);

async function readText(path) {
  return readFile(new URL(path, frontendRoot), "utf8");
}

const [
  popover,
  modelDialog,
  controller,
  draft,
  providerFields,
  modelFields,
  modelConfigLibrary,
  modelConfigApi,
  resumeTypes,
  agentSettingsTab,
  modelConfigPanel,
  modelConfigTable,
  modelConfigBulkDeleteAction,
  modelConfigSelection,
  dataTable,
  workspaceSkeletons,
  messages,
] =
  await Promise.all([
    readText("src/components/model-config-form-popover.tsx"),
    readText("src/components/models/model-config-dialog.tsx"),
    readText("src/components/models/use-model-config-dialog.ts"),
    readText("src/components/models/model-config-draft.ts"),
    readText("src/components/models/model-config-provider-fields.tsx"),
    readText("src/components/models/model-config-model-fields.tsx"),
    readText("src/lib/model-config.ts"),
    readText("src/lib/model-config-api.ts"),
    readText("src/types/resume.ts"),
    readText("src/components/agent-settings-tab.tsx"),
    readText("src/components/model-config-panel.tsx"),
    readText("src/components/models/model-config-table.tsx"),
    readText("src/components/models/model-config-bulk-delete-action.tsx"),
    readText("src/components/models/use-model-config-table-selection.ts"),
    readText("src/components/data-table.tsx"),
    readText("src/components/workspace-skeletons.tsx"),
    readText("src/i18n/locales/en.json").then(JSON.parse),
  ]);

assert.match(
  popover,
  /import\s*\{\s*ModelConfigDialog\s*\}\s*from\s*["']@\/components\/models\/model-config-dialog["']/,
  "The model dialog must load with its already-lazy route instead of replacing a Spinner surface after opening.",
);
assert.match(
  popover,
  /const \[dialogSession, setDialogSession\] = useState<number \| null>\([\s\S]*?defaultOpen \? 1 : null[\s\S]*?\)[\s\S]*?nextOpen && !open[\s\S]*?setDialogSession\(nextDialogSessionRef\.current\)/,
  "Provider metadata must stay deferred until the first dialog session opens, while each reopen receives a fresh form session.",
);
assert.match(
  popover,
  /\{dialogSession !== null \? \([\s\S]*?<ModelConfigDialog[\s\S]*?key=\{dialogSession\}/,
  "Closing the model dialog must leave its Radix content mounted long enough to run exit presence.",
);
assert.doesNotMatch(
  popover,
  /\{open \? \([\s\S]*?<ModelConfigDialog/,
  "The controlled open flag must not synchronously unmount Radix dialog content on close.",
);
assert.match(
  popover,
  /onExited=\{[\s\S]*?setDialogSession\(null\)/,
  "The deferred dialog controller must unmount after Radix finishes its exit animation.",
);
assert.match(
  modelDialog,
  /onExited:[\s\S]*?onAnimationEnd=\{[\s\S]*?dataset\.state === "closed"[\s\S]*?onExited\(\)/,
  "The dialog content must report its closed animation boundary before releasing the heavy controller.",
);
assert.match(
  modelDialog,
  /restoreFocus\?: \(\) => void[\s\S]*?onCloseAutoFocus=\{\(event\) => \{[\s\S]*?event\.preventDefault\(\)[\s\S]*?restoreFocus\(\)/,
  "A triggerless row edit dialog must explicitly return focus to its stable actions button.",
);
assert.doesNotMatch(
  popover,
  /\b(?:lazy|Suspense|LazyModelConfigDialog|loadModelConfigDialog)\b|<Spinner\b/,
  "Opening model configuration must render the final dialog directly, without a second lazy Spinner dialog.",
);
assert.match(
  popover,
  /defaultOpen = false[\s\S]*?useState\(defaultOpen\)[\s\S]*?defaultOpen \? 1 : null/,
  "A row action must be able to mount one already-open edit dialog without a transient empty frame.",
);
assert.match(
  popover,
  /trigger === undefined \?[\s\S]*?trigger === null \? null[\s\S]*?<Dialog[\s\S]*?\{triggerElement \? \([\s\S]*?<DialogTrigger asChild>/,
  "The create action must retain its default trigger while a row edit dialog may mount without a disposable menu trigger.",
);
assert.match(
  popover,
  /import \{[^}]*\bCopyPlus\b[^}]*\} from ["']lucide-react["'][\s\S]*?<CopyPlus data-icon="inline-start" \/>/,
  "The Add model trigger must use the same CopyPlus resource-create icon as the galleries.",
);

assert.match(
  modelConfigPanel,
  /<CardContent[\s\S]*?<ModelConfigFormPopover[\s\S]*?mode="create"[\s\S]*?\{configs\.length === 0 \? \(/,
  "The Add model trigger must stay in one stable parent outside the empty/table content switch.",
);
assert.doesNotMatch(
  modelConfigPanel,
  /const addModelAction\s*=/,
  "The same Add model element must not be moved between different React parents.",
);
assert.match(
  modelConfigTable,
  /getRowId=\{\(config\) => config\.id\}/,
  "Model table rows must use the persisted model config id instead of their array index.",
);
assert.match(
  modelConfigTable,
  /getRowClassName=\{\(config\) =>[\s\S]*?config\.id === enteringModelId[\s\S]*?animate-in[\s\S]*?fade-in/,
  "Only the newly created model row must receive the entry animation class.",
);
assert.doesNotMatch(
  modelConfigTable,
  /slide-in-from-top/,
  "New model feedback may fade in but must not move vertically like an expanding row.",
);
assert.match(
  modelConfigTable,
  /<span className="flex size-8 shrink-0 items-center justify-center">\s*<ModelProviderIcon/,
  "Model provider icons must keep a stable alignment box without adding a decorative background or border.",
);
assert.match(
  modelConfigTable,
  /accessorKey: 'model',[\s\S]*?header: \(\) => <span className="block pl-11">\{t\.model\}<\/span>[\s\S]*?className="flex size-8[\s\S]*?className="grid min-w-0/,
  "The model header must align with the primary model text after its icon alignment box.",
);
assert.match(
  modelConfigTable,
  /accessorKey: 'contextWindowTokens'[\s\S]*?className="block min-w-32 pr-2 text-right"[\s\S]*?className="flex min-w-32 justify-end pr-2"[\s\S]*?accessorKey: 'supportsImage'[\s\S]*?className="flex min-w-52 justify-center"[\s\S]*?className="flex min-w-52 justify-center gap-1\.5"/,
  "Context values must stay right aligned while the capability heading and badge group share a centered, separated column.",
);
assert.match(
  modelConfigTable,
  /function ModelConfigRowActions[\s\S]*?<DropdownMenu>[\s\S]*?<DropdownMenuTrigger asChild>[\s\S]*?data-\[state=open\]:bg-muted[\s\S]*?aria-label=\{t\.actions\}[\s\S]*?<EllipsisVertical \/>[\s\S]*?<DropdownMenuContent align="end" className="w-32">[\s\S]*?<DropdownMenuGroup>[\s\S]*?<DropdownMenuItem[\s\S]*?onEdit\(config, triggerRef\.current\)[\s\S]*?\{t\.editModelConfigAction\}[\s\S]*?<DropdownMenuSeparator \/>[\s\S]*?variant="destructive"[\s\S]*?onDelete\(config\.id\)[\s\S]*?\{t\.deleteModelConfigAction\}/,
  "Each model row must expose one accessible actions menu with text edit and destructive delete commands.",
);
assert.equal(
  messages.editModelConfigAction,
  "Edit",
  "The English model row edit command must stay concise without changing dialog titles.",
);
assert.equal(
  messages.deleteModelConfigAction,
  "Delete",
  "The English model row delete command must stay concise without changing dialog titles.",
);
assert.doesNotMatch(
  modelConfigTable,
  /\b(?:Pencil|Trash2)\b/,
  "Model row actions must not duplicate the text menu with standalone edit or delete icons.",
);
assert.match(
  modelConfigPanel,
  /\{editDialog \? \([\s\S]*?<ModelConfigFormPopover[\s\S]*?key=\{editDialog\.session\}[\s\S]*?mode="edit"[\s\S]*?defaultOpen[\s\S]*?initialConfig=\{editDialog\.config\}[\s\S]*?trigger=\{null\}/,
  "The edit dialog controller must remain outside the disposable dropdown content and remount for every row action.",
);
assert.match(
  `${modelConfigTable}\n${modelConfigPanel}`,
  /const triggerRef = useRef<HTMLButtonElement>\(null\)[\s\S]*?ref=\{triggerRef\}[\s\S]*?onEdit\(config, triggerRef\.current\)[\s\S]*?returnFocus,[\s\S]*?restoreFocus=\{\(\) => editDialog\.returnFocus\?\.focus\(\)\}/,
  "Closing a menu-launched edit dialog must restore keyboard focus to the row actions trigger.",
);
assert.match(
  dataTable,
  /getRowId\?:[\s\S]*?getRowClassName\?:[\s\S]*?enableRowSelection\?:[\s\S]*?rowSelection\?: RowSelectionState[\s\S]*?onRowSelectionChange\?: OnChangeFn<RowSelectionState>[\s\S]*?useReactTable\(\{[\s\S]*?enableRowSelection[\s\S]*?onRowSelectionChange[\s\S]*?state: rowSelection === undefined \? undefined : \{ rowSelection \}[\s\S]*?data-state=\{row\.getIsSelected\(\) \? 'selected' : undefined\}/,
  "The shared table must expose controlled TanStack row selection while retaining stable row identity and selected-row styling.",
);
assert.match(
  `${dataTable}\n${modelConfigTable}`,
  /tableClassName\?: string[\s\S]*?data-slot="data-table"[\s\S]*?w-full min-w-0 max-w-full overflow-hidden rounded-lg border bg-card[\s\S]*?<Table className=\{tableClassName\}>[\s\S]*?<TableHeader className="bg-muted">[\s\S]*?<TableHead key=\{header\.id\} scope="col">[\s\S]*?focus-within:bg-muted\/50[\s\S]*?<TableCell key=\{cell\.id\}>[\s\S]*?<DataTable[\s\S]*?tableClassName="min-w-\[760px\]"/,
  "The model data table must use the dashboard table surface and the shadcn primitive's default cell density.",
);
assert.doesNotMatch(
  dataTable,
  /rounded-\(--radius-card\)|shadow-card|h-11 px-4|h-14|px-4 py-2\.5/,
  "The model data table must not reintroduce the oversized card radius, shadow, or loose cell overrides.",
);
assert.match(
  modelConfigSelection,
  /export const MODEL_CONFIG_PAGE_SIZE = 10/,
  "Model table rows must retain their predictable ten-item page size.",
);
assert.match(
  modelConfigSelection,
  /const \{ currentPage, setCurrentPage \} = useGalleryUrlState\(\)[\s\S]*?const totalPages = Math\.max\([\s\S]*?Math\.ceil\(configs\.length \/ MODEL_CONFIG_PAGE_SIZE\)[\s\S]*?const safeCurrentPage = Math\.min\(currentPage, totalPages\)[\s\S]*?const pageConfigs = configs\.slice\([\s\S]*?pageStart \+ MODEL_CONFIG_PAGE_SIZE/,
  "Model pagination must preserve URL navigation, clamp the active page, and render one fixed-size slice.",
);
assert.match(
  modelConfigSelection,
  /const pageChanged = selection\.page !== safeCurrentPage[\s\S]*?useEffect\(\(\) => \{[\s\S]*?setSelection\(\{ page: safeCurrentPage, ids: \[\] \}\)[\s\S]*?\}, \[pageChanged, safeCurrentPage\]\)[\s\S]*?const selectedIds = pageChanged\s*\? \[\]/,
  "URL POP navigation must clear the previous page selection before it can flash or reappear when returning to that page.",
);
assert.match(
  modelConfigSelection,
  /function changePage\(page: number\) \{\s*setSelection\(\{ page, ids: \[\] \}\)\s*setCurrentPage\(page\)/,
  "Explicit pagination must clear row selection before updating the URL.",
);
assert.match(
  modelConfigTable,
  /id: 'select'[\s\S]*?getIsAllPageRowsSelected\(\)[\s\S]*?getIsSomePageRowsSelected\(\)[\s\S]*?'indeterminate'[\s\S]*?aria-label=\{t\.selectAll\}[\s\S]*?toggleAllPageRowsSelected\(checked === true\)[\s\S]*?checked=\{row\.getIsSelected\(\)\}[\s\S]*?row\.toggleSelected\(checked === true\)/,
  "The model table must use TanStack v8 page and row selection APIs through the installed shadcn Checkbox.",
);
assert.match(
  modelConfigBulkDeleteAction,
  /const canBulkDelete = selectedCount > 0[\s\S]*?data-slot="model-config-bulk-actions"[\s\S]*?aria-hidden=\{!canBulkDelete\}[\s\S]*?inert=\{!canBulkDelete\}[\s\S]*?tabIndex=\{canBulkDelete \? undefined : -1\}/,
  "Selecting any model must reveal the adjacent bulk delete action while collapsed controls remain inaccessible.",
);
assert.match(
  modelConfigBulkDeleteAction,
  /transition-\[opacity,transform\][\s\S]*?\[transition-duration:var\(--duration-enter\)\][\s\S]*?\[transition-timing-function:var\(--ease-move\)\][\s\S]*?\[transition-duration:var\(--duration-exit\)\][\s\S]*?ease-in/,
  "The bulk delete action must use the product's asymmetric enter and exit motion without changing the header layout.",
);
assert.doesNotMatch(
  modelConfigBulkDeleteAction,
  /transition-all|gridTemplateColumns|marginRight|scale\(|disabled=\{disabled \|\| !canBulkDelete\}/,
  "Bulk action feedback must not squeeze its label, animate spacing, scale the destructive button, or double-fade through its disabled state.",
);
assert.match(
  modelConfigPanel,
  /const pendingBulkModelIds = pendingBulkDeleteIds\.filter[\s\S]*?modelIds\.length === 0[\s\S]*?const response = await deleteModelConfigs\(modelIds\)[\s\S]*?selection\.clearSelection\(\)[\s\S]*?setPendingBulkDeleteIds\(\[\]\)[\s\S]*?open=\{pendingBulkModelIds\.length > 0\}[\s\S]*?title=\{t\.deleteModelConfigsConfirmTitle\}[\s\S]*?onConfirm=\{confirmBulkDeleteModels\}[\s\S]*?deferClose/,
  "A selected batch must issue one atomic helper call, clear selection after success, and use one deferred-close confirmation.",
);
assert.match(
  modelConfigApi,
  /function deleteModelConfigs\(ids: string\[\]\)[\s\S]*?`\$\{apiRoutes\.modelConfigs\}\/bulk-delete`[\s\S]*?method: 'POST'[\s\S]*?body: \{ ids \}/,
  "Bulk model deletion must use the POST /api/model-configs/bulk-delete contract.",
);
assert.doesNotMatch(
  `${modelConfigPanel}\n${modelConfigTable}\n${modelConfigSelection}`,
  /\b(?:DndContext|SortableContext|useSortable|draggable)\b/,
  "Model selection must not add drag-and-drop behavior.",
);
assert.match(
  modelConfigPanel,
  /data-slot="model-config-content"[\s\S]{0,140}className="flex min-h-\[390px\] min-w-0 flex-col gap-4"[\s\S]*?<ModelConfigTable[\s\S]*?configs=\{selection\.pageConfigs\}[\s\S]*?rowSelection=\{selection\.rowSelection\}[\s\S]*?onRowSelectionChange=\{selection\.onRowSelectionChange\}[\s\S]*?<GalleryPagination[\s\S]*?currentPage=\{selection\.currentPage\}[\s\S]*?totalPages=\{selection\.totalPages\}[\s\S]*?onPageChange=\{selection\.changePage\}/,
  "The model content must keep the recycle-bin baseline, grow with table rows, and paginate instead of scrolling internally.",
);
assert.doesNotMatch(
  modelConfigPanel,
  /100vh-12rem|model-config-table-scroll-area|overflow-auto/,
  "The model panel must not reserve a viewport-height surface or hide extra rows inside an internal scroller.",
);
assert.match(
  modelConfigPanel,
  /<Card className="[^"]*\bmin-w-0\b[^"]*\bpy-0\b[^"]*">\s*<CardContent className="grid min-w-0 gap-4 p-4">/,
  "The model surface must use the recycle-bin outer spacing instead of stacking Card and CardContent vertical padding.",
);
const modelConfigSkeletonSource = workspaceSkeletons.slice(
  workspaceSkeletons.indexOf("export function ModelConfigPanelSkeleton"),
  workspaceSkeletons.indexOf("function GalleryCardSkeleton"),
);
assert.match(
  modelConfigSkeletonSource,
  /data-slot="model-config-panel-skeleton"[\s\S]*?className="grid gap-4"[\s\S]*?data-slot="model-config-content-skeleton"[\s\S]*?className="flex min-h-\[390px\] min-w-0 flex-col gap-4"[\s\S]*?data-slot="data-table-skeleton"[\s\S]*?className="w-full min-w-0 max-w-full overflow-hidden rounded-lg border bg-card"/,
  "The model route skeleton must reserve the same compact baseline without a viewport-height cap.",
);
assert.match(
  modelConfigSkeletonSource,
  /<Table className="min-w-\[760px\]">[\s\S]*?<TableHeader className="bg-muted">[\s\S]*?<TableHead key=\{index\}>[\s\S]*?<TableRow key=\{rowIndex\} className="h-12">[\s\S]*?<TableCell key=\{columnIndex\}>/,
  "The model route skeleton must match the live table header and row geometry.",
);
assert.doesNotMatch(
  modelConfigSkeletonSource,
  /rounded-\(--radius-card\)|shadow-card|h-11 px-4|h-14|px-4 py-2\.5/,
  "The model route skeleton must not retain the table's previous loose card styling.",
);
assert.doesNotMatch(
  modelConfigSkeletonSource,
  /100vh|max-h-|overflow-auto/,
  "The model route skeleton must stay content-driven like the loaded panel.",
);
assert.match(
  modelConfigSkeletonSource,
  /<Card className="[^"]*\bmin-w-0\b[^"]*\bpy-0\b[^"]*">\s*<CardContent className="grid min-w-0 gap-4 p-4">/,
  "The model route skeleton must preserve the loaded surface's compact outer spacing.",
);

assert.match(
  controller,
  /void getModelProviders\(\)/,
  "The dialog controller must own provider metadata loading.",
);
assert.match(
  controller,
  /const \[modelOptionsLoaded, setModelOptionsLoaded\] = useState\(false\)/,
  "Cloud model options must begin provisional instead of flashing the saved-only seed.",
);
assert.match(
  controller,
  /const modelOptionsLoading =\s*!providersLoaded \|\| \(canDiscoverModels && !modelOptionsLoaded\)/,
  "The stable model-row loading state must cover both provider metadata and cached discovery.",
);
assert.match(
  controller,
  /discoverModels\(\{[\s\S]*apiUrl:\s*modelDiscoveryApiUrl/,
  "Model discovery must use the resolved provider API URL.",
);
const cachedDiscoveryCallIndex = controller.indexOf("void discoverModels({");
const cachedDiscoverySource = controller.slice(
  controller.lastIndexOf("useEffect(() => {", cachedDiscoveryCallIndex),
  controller.indexOf("const updateField"),
);
assert.match(
  cachedDiscoverySource,
  /setModelOptionsLoaded\(false\)[\s\S]*applyDiscoveredModels\(response\.models\);\s*setModelOptionsLoaded\(true\)[\s\S]*catch[\s\S]*setModelOptionsLoaded\(true\)/,
  "Cached discovery must keep one loading surface and settle it after either success or failure.",
);
assert.match(
  controller,
  /refresh:\s*true/,
  "Only explicit refreshes may bypass the cached model list.",
);
const providerSelectionSource = controller.slice(
  controller.indexOf("const selectProvider"),
  controller.indexOf("const selectModel"),
);
const explicitDiscoverySource = controller.slice(
  controller.indexOf("const refreshModels"),
  controller.indexOf("const submit"),
);
assert.match(
  controller,
  /const discoveryRequestIdRef = useRef\(0\)/,
  "Explicit model discovery must retain a latest-intent request identity outside render state.",
);
assert.match(
  providerSelectionSource,
  /discoveryRequestIdRef\.current \+= 1;[\s\S]*setDiscovering\(false\)/,
  "Switching providers must immediately invalidate an in-flight discovery request and clear its pending state.",
);
assert.match(
  explicitDiscoverySource,
  /const requestId = \+\+discoveryRequestIdRef\.current;/,
  "Every explicit discovery request must claim a new latest-intent identity.",
);
assert.match(
  explicitDiscoverySource,
  /if \(requestId !== discoveryRequestIdRef\.current\) \{\s*return;\s*\}\s*applyDiscoveredModels\(response\.models\)/,
  "A stale discovery response must not apply models to the newly selected provider.",
);
assert.ok(
  (explicitDiscoverySource.match(/requestId !== discoveryRequestIdRef\.current/g) ?? [])
    .length >= 2,
  "Stale model discovery failures must be ignored as well as stale successes.",
);
assert.match(
  explicitDiscoverySource,
  /if \(requestId === discoveryRequestIdRef\.current\) \{\s*setDiscovering\(false\);\s*\}/,
  "Only the latest model discovery request may settle the shared pending state.",
);
assert.match(
  controller,
  /models\.length === 1 \? models\[0\] : null/,
  "Discovery must only auto-select a model when exactly one result exists.",
);
assert.match(
  controller,
  /status:\s*"invalid",\s*errors:\s*nextErrors/,
  "Validation failures must expose the invalid fields to the submit handler.",
);
assert.match(
  modelDialog,
  /result\.status === "invalid"[\s\S]*?focusFirstModelConfigError\(/,
  "Invalid submission must focus the first invalid control inside the dialog form.",
);
assert.match(
  modelDialog,
  /<form[\s\S]*?ref=\{formRef\}/,
  "Invalid-field focus must stay scoped to the active model form.",
);
assert.match(
  modelDialog,
  /className="h-\[min\(34rem,calc\(100dvh-2rem\)\)\] overflow-hidden p-0 sm:max-w-xl"[\s\S]*?className="flex h-full min-h-0 flex-col"[\s\S]*?className="min-h-0 flex-1 gap-5 overflow-y-auto/,
  "The model dialog frame must stay fixed while only its form body scrolls.",
);

assert.match(
  draft,
  /provider\.id === "custom-cloud"[\s\S]*messages\.customCloudApi/,
  "The Custom Cloud API label must stay localized.",
);
assert.match(
  draft,
  /provider\.kind === "local"[\s\S]*messages\.localProvider[\s\S]*messages\.cloudProvider/,
  "Provider kind labels must distinguish local and cloud providers.",
);
assert.match(
  draft,
  /draft\.providerKind === "cloud"[\s\S]*provider\.defaultBaseUrl\.trim\(\)[\s\S]*draft\.apiUrl\.trim\(\)/,
  "Saved cloud configs must use the manifest URL while local configs keep the typed URL.",
);
assert.match(
  draft,
  /temperature:\s*null,[\s\S]*topP:\s*null/,
  "The form must not persist the removed sampling controls.",
);

assert.match(
  providerFields,
  /providersLoaded && draft\.providerKind !== "cloud"[\s\S]*name="model-api-url"/,
  "Only local/manual providers may expose a typed API URL.",
);
assert.match(
  providerFields,
  /providerDisplayLabel\([\s\S]*ProviderKindBadge/,
  "Provider options must share the localized label and kind badge.",
);
assert.match(
  providerFields,
  /<SelectTrigger[\s\S]*?id="model-provider"[\s\S]*?aria-invalid=\{Boolean\(errors\.provider\)\}/,
  "The provider trigger must expose its invalid state.",
);

assert.match(
  modelFields,
  /onValueChange=\{selectModel\}[\s\S]*className="w-full"[\s\S]*position="popper"/,
  "Cloud models must use the full-width discovered-model popper.",
);
assert.match(
  modelFields,
  /id="model-supports-tools"[\s\S]*updateField\("supportsTools", checked === true\)/,
  "Manual configs must preserve tool capability editing.",
);
assert.match(
  modelFields,
  /messages\.capabilities[\s\S]*messages\.advancedSettings[\s\S]*name="model-context-window"[\s\S]*name="model-max-tokens"/,
  "Manual configs must preserve capabilities and token limits.",
);
assert.match(
  modelFields,
  /<SelectTrigger[\s\S]*?id="model-select"[\s\S]*?aria-invalid=\{Boolean\(errors\.model \|\| errors\.discovery\)\}/,
  "The discovered-model trigger must expose its invalid state.",
);
assert.match(
  modelFields,
  /id="model-discovery"/,
  "The discovery action must remain an explicit focus fallback.",
);
assert.match(
  modelFields,
  /<Collapsible open=\{expanded\} onOpenChange=\{handleOpenChange\}>[\s\S]*?<CollapsibleContent[\s\S]*?className="model-output-settings-content"[\s\S]*?className="model-output-settings-content-inner pt-3"/,
  "Cloud advanced settings must reveal as one complete field instead of clipping through its controls.",
);
assert.match(
  modelFields,
  /closest<HTMLElement>[\s\S]*?viewport\.scrollTo\(\{[\s\S]*?prefers-reduced-motion: reduce/,
  "User-expanded advanced settings must scroll only the form viewport and respect reduced motion.",
);
assert.doesNotMatch(
  `${providerFields}\n${modelFields}`,
  /name="model-temperature"|name="model-top-p"/,
  "Removed temperature and topP controls must not return.",
);
assert.doesNotMatch(
  `${modelConfigLibrary}\n${resumeTypes}`,
  /\bLegacyModelConfig\b/,
  "The frontend must not retain a legacy model config type or normalization path.",
);
assert.match(
  resumeTypes,
  /interface ModelConfig[\s\S]*supportsThinking:\s*boolean/,
  "Saved model configs must preserve the self-hosted reasoning capability declaration.",
);
assert.match(
  modelConfigApi,
  /interface DiscoveredModel[\s\S]*supportsThinking:\s*boolean/,
  "Discovered models must preserve provider reasoning capability metadata.",
);
assert.match(
  agentSettingsTab,
  /const agentModelConfigs = modelConfigs\.filter\(\s*\(config\) => config\.supportsTools,?\s*\)[\s\S]*?agentModelConfigs\.find\(\s*\(config\) => config\.id === agentSettings\.defaultModelId,?\s*\)[\s\S]*?disabled=\{agentModelConfigs\.length === 0\}[\s\S]*?agentModelConfigs\.map\(\(config\) =>/,
  "Agent settings must list only tool-capable models and treat an unsupported saved selection as unconfigured.",
);
assert.doesNotMatch(
  `${resumeTypes}\n${modelConfigLibrary}\n${draft}\n${controller}\n${modelFields}`,
  /\bthinkingEnabled\b/,
  "The frontend model contract and settings flow must not restore a Thinking toggle.",
);

const server = await createServer({
  cacheDir: createViteTestCacheDir(),
  appType: "custom",
  configFile: false,
  logLevel: "silent",
  optimizeDeps: { noDiscovery: true },
  plugins: [
    {
      name: "model-config-dialog-trigger-stub",
      enforce: "pre",
      resolveId(source) {
        if (source === "@/components/model-provider-icon") {
          return "\0model-provider-icon-stub";
        }
        return source === "@/components/models/model-config-dialog"
          ? "\0model-config-dialog-trigger-stub"
          : null;
      },
      load(id) {
        if (
          id === "\0model-provider-icon-stub" ||
          id.endsWith("/components/model-provider-icon.tsx")
        ) {
          return "export function ModelProviderIcon() { return null }";
        }
        return id === "\0model-config-dialog-trigger-stub" ||
          id.endsWith("/components/models/model-config-dialog.tsx")
          ? "export function ModelConfigDialog() { return null }"
          : null;
      },
    },
  ],
  root: frontendRoot.pathname,
  server: { hmr: false, middlewareMode: true, ws: false },
  resolve: {
    alias: { "@": new URL("src/", frontendRoot).pathname },
  },
});

try {
  const { resolveSelectedModelIds } = await server.ssrLoadModule(
    "/src/components/models/use-model-config-table-selection.ts",
  );
  assert.deepEqual(
    resolveSelectedModelIds(
      { page: 2, ids: ["model-a", "removed-model", "model-b"] },
      2,
      [{ id: "model-b" }, { id: "model-a" }],
    ),
    ["model-a", "model-b"],
    "Selection must retain stable IDs in selection order while pruning rows removed or moved off the current page.",
  );
  assert.deepEqual(
    resolveSelectedModelIds(
      { page: 1, ids: ["model-a", "model-b"] },
      2,
      [{ id: "model-a" }, { id: "model-b" }],
    ),
    [],
    "A URL page change must make the previous page selection unavailable before the clearing effect settles.",
  );

  const { classifyModelConfigSaveFailure } = await server.ssrLoadModule(
    "/src/components/models/use-model-config-dialog.ts",
  );
  const backendOutputLimitError = Object.assign(
    new Error("The output limit exceeds this model's maximum."),
    { apiCode: "MODEL_CONFIG_MAX_TOKENS_EXCEEDS_LIMIT" },
  );
  assert.deepEqual(
    classifyModelConfigSaveFailure(backendOutputLimitError, {
      validationRequired: "Required",
    }),
    {
      status: "invalid",
      errors: {
        maxTokens: "The output limit exceeds this model's maximum.",
      },
    },
    "A backend-discovered output ceiling must return field validation so the dialog can reveal and focus the override.",
  );
  const backendInvalidOutputError = Object.assign(
    new Error("Enter an integer greater than 0."),
    { apiCode: "MODEL_CONFIG_MAX_TOKENS_INVALID" },
  );
  assert.deepEqual(
    classifyModelConfigSaveFailure(backendInvalidOutputError, {
      validationRequired: "Required",
    }),
    {
      status: "invalid",
      errors: { maxTokens: "Enter an integer greater than 0." },
    },
    "Backend output-format validation must use the same field-level invalid result.",
  );
  assert.deepEqual(
    classifyModelConfigSaveFailure(new Error("Save failed"), {
      validationRequired: "Required",
    }),
    {
      status: "failed",
      errors: { discovery: "Save failed" },
    },
    "Unrelated save failures must retain the existing generic form feedback.",
  );

  const { focusFirstModelConfigError } = await server.ssrLoadModule(
    "/src/components/models/model-config-focus.ts",
  );
  const focusedIds = [];
  const focusTargets = new Map(
    [
      "model-api-key",
      "model-select",
      "model-discovery",
      "model-max-tokens",
      "model-output-settings",
    ].map((id) => [
      `#${id}`,
      {
        disabled: id === "model-select",
        focus() {
          focusedIds.push(id);
        },
      },
    ]),
  );
  const focusRoot = {
    querySelector(selector) {
      return focusTargets.get(selector) ?? null;
    },
  };
  assert.equal(
    focusFirstModelConfigError(
      focusRoot,
      { apiKey: "Required", model: "Required" },
      "cloud",
    ),
    true,
  );
  assert.deepEqual(
    focusedIds,
    ["model-api-key"],
    "Cloud validation must focus the API key before the later model control.",
  );
  focusedIds.length = 0;
  assert.equal(
    focusFirstModelConfigError(
      focusRoot,
      { model: "Required", discovery: "Fetch models" },
      "cloud",
    ),
    true,
  );
  assert.deepEqual(
    focusedIds,
    ["model-discovery"],
    "A disabled model select must fall back to the model discovery action.",
  );
  focusedIds.length = 0;
  assert.equal(
    focusFirstModelConfigError(
      focusRoot,
      { maxTokens: "Exceeds model maximum" },
      "cloud",
    ),
    true,
  );
  assert.deepEqual(
    focusedIds,
    ["model-max-tokens"],
    "An expanded cloud output error must focus the invalid input itself.",
  );
  focusTargets.delete("#model-max-tokens");
  focusedIds.length = 0;
  assert.equal(
    focusFirstModelConfigError(
      focusRoot,
      { maxTokens: "Exceeds model maximum" },
      "cloud",
    ),
    true,
  );
  assert.deepEqual(
    focusedIds,
    ["model-output-settings"],
    "Before the expanded field mounts, cloud output validation must retain a reliable trigger fallback.",
  );

  const { normalizeModelConfigs } = await server.ssrLoadModule(
    "/src/lib/model-config.ts",
  );
  assert.deepEqual(
    normalizeModelConfigs(
      {
        modelConfig: {
          provider: "openai",
          model: "legacy-model",
        },
      },
      "en",
    ),
    [],
    "The removed singular modelConfig field must not hydrate workspace models.",
  );
  const canonicalModelConfig = {
    id: "model-canonical",
    provider: "openai",
    providerLabel: "OpenAI",
    iconProvider: "openai",
    providerKind: "cloud",
    apiFamily: "openai_responses",
    nickname: "Primary model",
    apiKeyPreview: "sk-••••",
    model: "gpt-test",
    apiUrl: "https://api.openai.com/v1",
    temperature: null,
    topP: null,
    maxTokens: 4096,
    contextWindowTokens: 128000,
    supportsImage: true,
    supportsThinking: true,
    supportsTools: true,
    supportsStreaming: true,
  };
  assert.deepEqual(
    normalizeModelConfigs({ modelConfigs: [canonicalModelConfig] }, "en"),
    [canonicalModelConfig],
    "The canonical modelConfigs array must remain the workspace model contract.",
  );

  const { AgentSettingsTab } = await server.ssrLoadModule(
    "/src/components/agent-settings-tab.tsx",
  );
  const { Tabs } = await server.ssrLoadModule("/src/components/ui/tabs.tsx");
  const unsupportedSelectedModel = {
    ...canonicalModelConfig,
    id: "model-without-tools",
    nickname: "No-tools model",
    supportsTools: false,
  };
  const agentSettingsMarkup = renderToStaticMarkup(
    React.createElement(
      Tabs,
      { value: "agent" },
      React.createElement(AgentSettingsTab, {
        agentSettings: {
          defaultModelId: unsupportedSelectedModel.id,
          responseLanguage: "follow",
          behaviorMode: "balanced",
          confirmationMode: "always",
        },
        modelConfigs: [unsupportedSelectedModel, canonicalModelConfig],
        onAgentSettingsChange() {},
        t: messages,
      }),
    ),
  );
  assert.match(
    agentSettingsMarkup,
    new RegExp(messages.agentModelNotConfigured),
    "An unsupported saved Agent model must render the clear unconfigured state.",
  );
  assert.doesNotMatch(
    agentSettingsMarkup,
    /No-tools model/,
    "An unsupported saved model must not remain visible as the active Agent model.",
  );

  const {
    applyDiscoveredModel,
    createModelConfigDraft,
    createSavedModelConfig,
    discoveredFromConfig,
    validateModelConfigDraft,
  } =
    await server.ssrLoadModule(
      "/src/components/models/model-config-draft.ts",
    );
  const discoveredCloudModel = {
    id: "gpt-test",
    label: "GPT Test",
    contextWindowTokens: 128000,
    maxOutputTokens: 65536,
    supportsImage: true,
    supportsThinking: true,
    supportsTools: true,
    supportsStreaming: true,
    metadataSource: "provider",
  };
  const cloudProvider = {
    id: "openai",
    kind: "cloud",
    label: "OpenAI",
    iconProvider: "openai",
    defaultBaseUrl: "https://api.openai.com/v1",
    authRequired: false,
  };
  const validationMessages = {
    validationRequired: "Required",
    modelDiscoveryFailed: "Discovery failed",
    modelDiscoveryRequired: "Select a discovered model",
    validationMaxTokens: "Enter a positive integer",
    validationMaxTokensExceeded: "Must not exceed {count}",
  };
  const autoOutputDraft = applyDiscoveredModel(
    {
      ...createModelConfigDraft("en"),
      provider: "openai",
      providerKind: "cloud",
      maxTokens: "8192",
    },
    discoveredCloudModel,
  );
  assert.equal(
    autoOutputDraft.maxTokens,
    "",
    "Selecting a different cloud model must reset the request override to Auto instead of copying its capability ceiling.",
  );
  const refreshedOutputDraft = applyDiscoveredModel(
    { ...autoOutputDraft, maxTokens: "8192" },
    discoveredCloudModel,
  );
  assert.equal(
    refreshedOutputDraft.maxTokens,
    "8192",
    "Refreshing capability metadata for the selected model must preserve its explicit output override.",
  );
  assert.equal(
    discoveredFromConfig(canonicalModelConfig)[0]?.maxOutputTokens,
    null,
    "A saved request override must never masquerade as the model capability ceiling before discovery completes.",
  );
  const savedModelConfig = createSavedModelConfig(
    {
      ...createModelConfigDraft("en"),
      provider: "openai",
      providerKind: "cloud",
      apiFamily: "openai_responses",
      model: "gpt-test",
      maxTokens: "8192",
      contextWindowTokens: "128000",
      supportsThinking: true,
    },
    cloudProvider,
  );
  assert.equal(
    savedModelConfig.supportsThinking,
    true,
    "Saved model configs must preserve the declared reasoning capability.",
  );
  assert.equal(
    savedModelConfig.maxTokens,
    8192,
    "Cloud configs must persist an explicit output override instead of forcing Auto.",
  );
  assert.equal(
    createSavedModelConfig(
      { ...createModelConfigDraft("en"), providerKind: "cloud" },
      cloudProvider,
    ).maxTokens,
    null,
    "An empty cloud output override must remain null so runtime Auto policy stays active.",
  );
  const invalidCloudOutputErrors = validateModelConfigDraft(
    { ...autoOutputDraft, maxTokens: "0" },
    cloudProvider,
    [discoveredCloudModel],
    validationMessages,
  );
  assert.equal(
    invalidCloudOutputErrors.maxTokens,
    "Enter a positive integer",
    "Cloud output overrides must reject non-positive values before submission.",
  );
  const excessiveCloudOutputErrors = validateModelConfigDraft(
    { ...autoOutputDraft, maxTokens: "65537" },
    cloudProvider,
    [discoveredCloudModel],
    validationMessages,
  );
  assert.equal(
    excessiveCloudOutputErrors.maxTokens,
    "Must not exceed 65536",
    "A known model output ceiling must bound the cloud override.",
  );
  const unknownCloudOutputErrors = validateModelConfigDraft(
    { ...autoOutputDraft, maxTokens: "131072" },
    cloudProvider,
    [{ ...discoveredCloudModel, maxOutputTokens: null }],
    validationMessages,
  );
  assert.equal(
    unknownCloudOutputErrors.maxTokens,
    undefined,
    "Unknown model capability must not invent an output ceiling for a valid positive override.",
  );
  const unsafeCloudOutputErrors = validateModelConfigDraft(
    { ...autoOutputDraft, maxTokens: "9007199254740992" },
    cloudProvider,
    [{ ...discoveredCloudModel, maxOutputTokens: null }],
    validationMessages,
  );
  assert.equal(
    unsafeCloudOutputErrors.maxTokens,
    "Enter a positive integer",
    "Unknown model capability must still reject values outside JavaScript's safe integer range.",
  );
  assert.equal(
    Object.hasOwn(savedModelConfig, "thinkingEnabled"),
    false,
    "Saved model configs must not send a Thinking toggle.",
  );

  const { ModelConfigModelFields } = await server.ssrLoadModule(
    "/src/components/models/model-config-model-fields.tsx",
  );
  const renderCloudFields = (
    maxTokens,
    errors = {},
    discoveredModels = [discoveredCloudModel],
    modelOptionsLoading = false,
  ) =>
    renderToStaticMarkup(
      React.createElement(ModelConfigModelFields, {
        controller: {
          canDiscoverModels: false,
          discovering: false,
          discoveredModels,
          draft: {
            ...createModelConfigDraft("en"),
            provider: "openai",
            providerKind: "cloud",
            apiFamily: "openai_responses",
            model: "gpt-test",
            maxTokens,
            contextWindowTokens: "128000",
            supportsThinking: true,
          },
          errors,
          modelOptionsLoading,
          providersLoaded: true,
          refreshModels() {},
          selectModel() {},
          selectedProvider: {},
          updateField() {},
        },
        messages: {
          model: "Model",
          modelDiscoverySelectFetched: "Select a model",
          modelDiscoveryRequired: "Fetch models",
          fetchingModels: "Fetching",
          refreshModels: "Refresh",
          fetchModels: "Fetch",
          advancedSettings: "Advanced Settings",
          maxTokens: "max_tokens",
          maxTokensAuto: "Auto (recommended)",
        },
      }),
    );
  const loadingCloudFieldsMarkup = renderCloudFields(
    "",
    {},
    [discoveredCloudModel],
    true,
  );
  assert.match(
    loadingCloudFieldsMarkup,
    /data-slot="skeleton"/,
    "Cached cloud model discovery must keep the model row on its stable Skeleton until the full catalog settles.",
  );
  assert.doesNotMatch(
    loadingCloudFieldsMarkup,
    /id="model-select"|id="model-output-settings"|GPT Test/,
    "A saved-only provisional model must not flash as an interactive field before cached discovery settles.",
  );
  const cloudFieldsMarkup = renderCloudFields("8192");
  assert.doesNotMatch(
    cloudFieldsMarkup,
    /model-thinking-enabled|Enable Thinking/,
    "Cloud model settings must not expose a Thinking toggle.",
  );
  assert.doesNotMatch(
    cloudFieldsMarkup,
    /model-context-window|model-temperature|model-top-p/,
    "Cloud advanced settings must not expose provider-managed context or sampling controls.",
  );
  assert.match(
    cloudFieldsMarkup,
    /id="model-output-settings"[\s\S]*Advanced Settings[\s\S]*max_tokens[\s\S]*id="model-max-tokens"/,
    "A selected cloud model must expose the flat advanced-settings trigger and max_tokens field.",
  );
  assert.match(
    cloudFieldsMarkup,
    /<input[^>]*type="text"[^>]*data-slot="input"[^>]*id="model-max-tokens"[^>]*inputMode="numeric"[^>]*placeholder="Auto \(recommended\)"/,
    "The max_tokens override must use the native shadcn Input without browser number steppers.",
  );
  assert.doesNotMatch(
    cloudFieldsMarkup,
    /Output length:|Leave blank for Auto|Model maximum:|rounded-lg border/,
    "Cloud advanced settings must not render a card or explanatory subtitles.",
  );
  const autoCloudFieldsMarkup = renderCloudFields("");
  assert.match(
    autoCloudFieldsMarkup,
    /id="model-output-settings"[\s\S]*Advanced Settings/,
    "The collapsed cloud settings trigger must retain its concise label.",
  );
  assert.doesNotMatch(
    autoCloudFieldsMarkup,
    /Output length:/,
    "The collapsed cloud settings trigger must not render a status subtitle.",
  );
  const unknownCapabilityFieldsMarkup = renderCloudFields("", {}, []);
  assert.match(
    unknownCapabilityFieldsMarkup,
    /id="model-output-settings"[\s\S]*Advanced Settings/,
    "An existing cloud model must keep its output override available while capability discovery is unavailable.",
  );
  assert.doesNotMatch(
    unknownCapabilityFieldsMarkup,
    /Model maximum:/,
    "A missing discovery result must not invent a model output ceiling.",
  );
  const invalidCloudFieldsMarkup = renderCloudFields("65537", {
    maxTokens: "Must not exceed the model maximum (65536).",
  });
  assert.match(
    invalidCloudFieldsMarkup,
    /id="model-max-tokens"[\s\S]*aria-describedby="model-max-tokens-error"/,
    "The output input must expose its visible validation message to assistive technology.",
  );
  assert.match(
    invalidCloudFieldsMarkup,
    /id="model-max-tokens-error"[\s\S]*Must not exceed the model maximum \(65536\)\./,
    "The output error must retain its stable id while the validation section is expanded.",
  );
  assert.doesNotMatch(
    invalidCloudFieldsMarkup,
    /model-max-tokens-auto-hint|model-max-tokens-maximum/,
    "Removed subtitles must not remain as hidden or visible description nodes.",
  );

  const { ModelConfigFormPopover } = await server.ssrLoadModule(
    "/src/components/model-config-form-popover.tsx",
  );
  const createTriggerMarkup = renderToStaticMarkup(
    React.createElement(ModelConfigFormPopover, {
      locale: "en",
      mode: "create",
      onSubmit() {},
      t: { addModelConfig: "Add model" },
    }),
  );
  const editTriggerMarkup = renderToStaticMarkup(
    React.createElement(ModelConfigFormPopover, {
      locale: "en",
      mode: "edit",
      onSubmit() {},
      t: { addModelConfig: "Add model" },
      trigger: React.createElement("button", { type: "button" }, "Edit model"),
    }),
  );

  for (const [label, triggerMarkup] of [
    ["add-model", createTriggerMarkup],
    ["edit-model", editTriggerMarkup],
  ]) {
    assert.match(
      triggerMarkup,
      /aria-haspopup="dialog"/,
      `The rendered ${label} button must receive the Radix dialog trigger behavior.`,
    );
    assert.match(
      triggerMarkup,
      /aria-expanded="false"/,
      `The rendered ${label} button must expose its closed dialog state.`,
    );
  }
} finally {
  await server.close();
}

console.log("Model config boundaries verified.");
