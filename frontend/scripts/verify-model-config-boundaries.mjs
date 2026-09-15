import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const frontendRoot = new URL("../", import.meta.url);
const readText = (path) => readFile(new URL(path, frontendRoot), "utf8");

const [
  popover,
  modelDialog,
  controller,
  draft,
  providerFields,
  modelFields,
  advancedSettingsField,
  thinkingModeField,
  modelConfigLibrary,
  modelConfigApi,
  resumeTypes,
  modelConfigPanel,
  modelConfigTable,
  modelConfigBulkDeleteAction,
  modelConfigSelection,
  dataTable,
  workspaceSkeletons,
] = await Promise.all([
  readText("src/components/model-config-form-popover.tsx"),
  readText("src/components/models/model-config-dialog.tsx"),
  readText("src/components/models/use-model-config-dialog.ts"),
  readText("src/components/models/model-config-draft.ts"),
  readText("src/components/models/model-config-provider-fields.tsx"),
  readText("src/components/models/model-config-model-fields.tsx"),
  readText("src/components/models/model-config-advanced-settings-field.tsx"),
  readText("src/components/models/model-config-thinking-mode-field.tsx"),
  readText("src/lib/model-config.ts"),
  readText("src/lib/model-config-api.ts"),
  readText("src/types/resume.ts"),
  readText("src/components/model-config-panel.tsx"),
  readText("src/components/models/model-config-table.tsx"),
  readText("src/components/models/model-config-bulk-delete-action.tsx"),
  readText("src/components/models/use-model-config-table-selection.ts"),
  readText("src/components/data-table.tsx"),
  readText("src/components/workspace-skeletons.tsx"),
]);

assert.match(
  popover,
  /import\s*\{\s*ModelConfigDialog\s*\}\s*from\s*["']@\/components\/models\/model-config-dialog["']/,
  "The model dialog must load with its already-lazy route instead of replacing a Spinner surface after opening.",
);

assert.doesNotMatch(
  popover,
  /\b(?:lazy|Suspense|LazyModelConfigDialog|loadModelConfigDialog)\b|<Spinner\b/,
  "Opening model configuration must render the final dialog directly, without a second lazy Spinner dialog.",
);

assert.match(
  popover,
  /import \{[^}]*\bCopyPlus\b[^}]*\} from ["']lucide-react["'][\s\S]*?<CopyPlus data-icon="inline-start" \/>/,
  "The Add model trigger must use the same CopyPlus resource-create icon as the galleries.",
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
  /accessorKey: ["']model["'],[\s\S]*?header: \(\) => <span className="block pl-11">\{t\.model\}<\/span>[\s\S]*?className="flex size-8[\s\S]*?className="grid min-w-0/,
  "The model header must align with the primary model text after its icon alignment box.",
);

assert.match(
  modelConfigTable,
  /accessorKey: ["']contextWindowTokens["'][\s\S]*?className="block min-w-32 pr-2 text-right"[\s\S]*?className="flex min-w-32 justify-end pr-2"[\s\S]*?accessorKey: ["']supportsImage["'][\s\S]*?className="flex min-w-52 justify-center"[\s\S]*?className="flex min-w-52 justify-center gap-1\.5"/,
  "Context values must stay right aligned while the capability heading and badge group share a centered, separated column.",
);

assert.doesNotMatch(
  modelConfigTable,
  /\b(?:Pencil|Trash2)\b/,
  "Model row actions must not duplicate the text menu with standalone edit or delete icons.",
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
  modelConfigBulkDeleteAction,
  /transition-\[opacity,transform\][\s\S]*?\[transition-duration:var\(--duration-enter\)\][\s\S]*?\[transition-timing-function:var\(--ease-move\)\][\s\S]*?\[transition-duration:var\(--duration-exit\)\][\s\S]*?ease-in/,
  "The bulk delete action must use the product's asymmetric enter and exit motion without changing the header layout.",
);

assert.doesNotMatch(
  modelConfigBulkDeleteAction,
  /transition-all|gridTemplateColumns|marginRight|scale\(|disabled=\{disabled \|\| !canBulkDelete\}/,
  "Bulk action feedback must not squeeze its label, animate spacing, scale the destructive button, or double-fade through its disabled state.",
);

assert.doesNotMatch(
  `${modelConfigPanel}\n${modelConfigTable}\n${modelConfigSelection}`,
  /\b(?:DndContext|SortableContext|useSortable|draggable)\b/,
  "Model selection must not add drag-and-drop behavior.",
);

assert.match(
  modelConfigPanel,
  /data-slot="model-config-content"[\s\S]{0,140}className="flex min-h-\[390px\] min-w-0 flex-col gap-4"[\s\S]*?<ModelConfigTable[\s\S]*?<GalleryPagination/,
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
  workspaceSkeletons.indexOf("export function WorkspaceRouteSkeleton"),
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
  modelDialog,
  /className="h-\[min\(34rem,calc\(100dvh-2rem\)\)\] overflow-hidden p-0 sm:max-w-xl[^"]*"[\s\S]*?className="flex h-full min-h-0 flex-col"[\s\S]*?className="min-h-0 flex-1 gap-5 overflow-y-auto/,
  "The model dialog frame must stay fixed while only its form body scrolls.",
);

assert.match(
  modelDialog,
  /\[&>\[data-slot=dialog-close\]\]:inline-flex[\s\S]*?\[&>\[data-slot=dialog-close\]\]:size-8[\s\S]*?\[&>\[data-slot=dialog-close\]\]:items-center[\s\S]*?\[&>\[data-slot=dialog-close\]\]:justify-center/,
  "The model dialog close control must keep a compact touch target aligned with the title.",
);

assert.match(
  providerFields,
  /<ProviderKindBadge>/,
  "Provider options must use the shared kind badge component.",
);

assert.match(
  modelFields,
  /<SelectTrigger[\s\S]*className="w-full"[\s\S]*position="popper"/,
  "Cloud models must use the full-width discovered-model popper.",
);

assert.match(
  advancedSettingsField,
  /<Collapsible\b[\s\S]*?<CollapsibleContent[\s\S]*?className="model-output-settings-content"[\s\S]*?className="model-output-settings-content-inner gap-5 pt-3"/,
  "Advanced settings must reveal as one complete field instead of clipping through its controls.",
);

assert.match(
  advancedSettingsField,
  /function ModelConfigAdvancedSettingsField[\s\S]*?<Field\s+orientation="horizontal"\s+className="flex-wrap gap-x-3 gap-y-1\.5"[\s\S]*?htmlFor="model-max-tokens"[\s\S]*?<Input[\s\S]*?id="model-max-tokens"[\s\S]*?className="w-32 max-w-\[55%\] shrink-0"[\s\S]*?<FieldError[\s\S]*?className="basis-full"/,
  "Cloud max_tokens must use a compact right-aligned input while its error keeps a full row.",
);

assert.match(
  thinkingModeField,
  /import \{ Switch \} from "@\/components\/ui\/switch";[\s\S]*<Switch/,
  "Thinking mode must use the installed shadcn Switch.",
);

assert.doesNotMatch(
  thinkingModeField,
  /FieldDescription|thinkingMode(?:Auto|Off|Managed|OffHint|ManagedHint)|ToggleGroup/,
  "The Switch row must not retain the removed mode buttons or explanatory copy.",
);

assert.doesNotMatch(
  `${modelConfigLibrary}\n${resumeTypes}`,
  /\bLegacyModelConfig\b/,
  "The frontend must not retain a legacy model config type or normalization path.",
);

assert.match(
  resumeTypes,
  /type ThinkingMode = ["']auto["'] \| ["']off["'][\s\S]*interface ModelConfig[\s\S]*supportsThinking:\s*boolean[\s\S]*thinkingMode:\s*ThinkingMode[\s\S]*availableThinkingModes:\s*ThinkingMode\[\]/,
  "Saved model configs must distinguish the thinking capability, user preference, and currently available modes.",
);

assert.match(
  modelConfigApi,
  /interface DiscoveredModel[\s\S]*supportsThinking:\s*boolean[\s\S]*availableThinkingModes:\s*ModelConfig\[["']availableThinkingModes["']\]/,
  "Discovered models must preserve provider-authoritative thinking mode metadata.",
);

assert.match(
  modelConfigApi,
  /Omit<ModelConfig, ["']id["'] \| ["']availableThinkingModes["']>/,
  "Model saves must submit the user preference without echoing server-derived mode capabilities.",
);

assert.doesNotMatch(
  `${resumeTypes}\n${modelConfigLibrary}\n${draft}\n${controller}\n${modelFields}`,
  /\bthinkingEnabled\b/,
  "The frontend must not collapse capability-aware thinking modes back into a misleading boolean toggle.",
);

console.log("Model config architecture and layout verified.");
