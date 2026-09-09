import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const projectRoot = new URL("../", import.meta.url);
const [
  packageSource,
  themeSource,
  dialogSource,
  alertDialogSource,
  selectSource,
  appToasterSource,
  resumeDetailCommandsSource,
  cardSource,
  authPageShellSource,
  templateEditorSource,
  copilotPanelShellSource,
  copilotChangeSummarySource,
  draftReviewComparisonSource,
  pdfExportRendererSource,
  modelConfigPanelSource,
  workspaceSkeletonsSource,
  gallerySkeletonsSource,
  documentPreviewCardSource,
  settingsWorkspacePageSource,
  settingsPanelSkeletonSource,
  templateDetailWorkspaceViewSource,
  resumeGalleryCardSource,
  templateGalleryCardSource,
  resumeGallerySource,
  templateGallerySource,
  recycleBinPanelSource,
] = await Promise.all([
  readFile(new URL("package.json", projectRoot), "utf8"),
  readFile(new URL("src/index.css", projectRoot), "utf8"),
  readFile(new URL("src/components/ui/dialog.tsx", projectRoot), "utf8"),
  readFile(new URL("src/components/ui/alert-dialog.tsx", projectRoot), "utf8"),
  readFile(new URL("src/components/ui/select.tsx", projectRoot), "utf8"),
  readFile(new URL("src/components/app-toaster.tsx", projectRoot), "utf8"),
  readFile(
    new URL(
      "src/components/workspace/use-resume-detail-commands.ts",
      projectRoot,
    ),
    "utf8",
  ),
  readFile(new URL("src/components/ui/card.tsx", projectRoot), "utf8"),
  readFile(
    new URL("src/components/auth/auth-page-shell.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/templates/template-editor.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/copilot/copilot-panel-shell.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/copilot/copilot-change-summary.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL(
      "src/components/preview/resume-draft-review-comparison.tsx",
      projectRoot,
    ),
    "utf8",
  ),
  readFile(
    new URL("src/components/pdf-export-renderer.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/model-config-panel.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/workspace-skeletons.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/gallery-skeletons.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/preview/document-canvas.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL(
      "src/components/workspace/settings-workspace-page.tsx",
      projectRoot,
    ),
    "utf8",
  ),
  readFile(
    new URL("src/components/settings-panel-skeleton.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL(
      "src/components/workspace/template-detail-workspace-view.tsx",
      projectRoot,
    ),
    "utf8",
  ),
  readFile(
    new URL("src/components/resume-gallery-card.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/templates/template-gallery-card.tsx", projectRoot),
    "utf8",
  ),
  readFile(new URL("src/components/resume-gallery.tsx", projectRoot), "utf8"),
  readFile(
    new URL("src/components/templates/template-gallery.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/recycle-bin-panel.tsx", projectRoot),
    "utf8",
  ),
]);
const packageJson = JSON.parse(packageSource);

assert(
  packageJson.devDependencies?.["tw-animate-css"],
  "The shadcn animation styles must remain installed.",
);
assert(
  themeSource.includes('@import "tw-animate-css";'),
  "The global stylesheet must load the shadcn animation styles.",
);
for (const motionClass of ["dialog-overlay-motion", "dialog-content-motion"]) {
  assert(
    dialogSource.includes(motionClass) &&
      alertDialogSource.includes(motionClass),
    `Dialog and AlertDialog must share ${motionClass}.`,
  );
}
assert(
  !alertDialogSource.includes("data-[state=open]:animate-in") &&
    !alertDialogSource.includes("data-[state=closed]:animate-out") &&
    !alertDialogSource.includes("duration-200"),
  "AlertDialog must not override the shared product dialog motion.",
);
assert(
  themeSource.includes("--color-input: var(--input);") &&
    (themeSource.match(/^\s*--input:/gm) ?? []).length === 2,
  "The input token must be mapped and defined for light and dark themes.",
);
assert(
  themeSource
    .match(/\.dark\s*\{[\s\S]*?\}/)?.[0]
    .includes("--input: oklch(1 0 0 / 15%);"),
  "The dark input token must retain shadcn's translucent control border.",
);
for (const radiusToken of [
  "--radius-sm: calc(var(--radius) * 0.6);",
  "--radius-md: calc(var(--radius) * 0.8);",
  "--radius-lg: var(--radius);",
  "--radius-xl: calc(var(--radius) * 1.4);",
]) {
  assert(
    themeSource.includes(radiusToken),
    `The shadcn radius scale is missing ${radiusToken}`,
  );
}
const surfaceRadiusValues = ["card", "workspace", "preview"].map((surface) => {
  const value = themeSource.match(
    new RegExp(`--radius-${surface}:\\s*([\\d.]+)rem;`),
  )?.[1];
  assert(value, `The product surface scale is missing --radius-${surface}.`);
  return Number(value);
});
assert(
  surfaceRadiusValues[0] < surfaceRadiusValues[1] &&
    surfaceRadiusValues[1] < surfaceRadiusValues[2],
  "Card, workspace, and preview radii must retain a visible semantic hierarchy.",
);
assert(
  themeSource.includes("--shadow-card: var(--surface-shadow-card);"),
  "The product surface scale is missing the card elevation token.",
);
assert.equal(
  (themeSource.match(/^\s*--surface-shadow-card:/gm) ?? []).length,
  2,
  "The card elevation must be defined for both light and dark themes.",
);
assert(
  cardSource.includes("rounded-(--radius-card)") &&
    cardSource.includes("shadow-card"),
  "Card must provide the shared content-surface radius and elevation.",
);
const authShellCardClassName =
  authPageShellSource.match(/<Card className="([^"]*)"/)?.[1] ?? "";
assert(
  authShellCardClassName.includes("rounded-(--radius-workspace)") &&
    authShellCardClassName.includes("shadow-none") &&
    !/rounded-\[(?:30|32)px\]|shadow-xl|shadow-\[/.test(authShellCardClassName),
  "The auth shell must use the shared flat workspace surface.",
);
assert(
  templateEditorSource.includes('data-slot="template-editor"') &&
    !templateEditorSource.includes("<Card"),
  "The template editor must use the shared cardless inspector surface.",
);
assert(
  copilotPanelShellSource.includes("rounded-(--radius-card)") &&
    copilotPanelShellSource.includes("shadow-card") &&
    themeSource.includes(`.app-shell--document .agent-panel-card {
    height: 100%;
    max-height: 100%;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }`),
  "The Agent panel must retain compact card chrome and meet the desktop workspace edges.",
);
assert(
  modelConfigPanelSource.includes(
    "rounded-(--radius-workspace) border-border/80 bg-muted/35 shadow-none",
  ) &&
    /function ModelConfigPanelSkeleton[\s\S]*?<Card className="[^"]*rounded-\(--radius-workspace\)[^"]*bg-muted\/35[^"]*shadow-none/.test(
      workspaceSkeletonsSource,
    ),
  "The model workspace and its skeleton must share the muted flat workspace surface.",
);
assert(
  documentPreviewCardSource.includes("rounded-(--radius-preview)") &&
    /function WorkspacePreviewSkeleton[\s\S]*?rounded-\(--radius-preview\)/.test(
      workspaceSkeletonsSource,
    ),
  "The recycle-bin document preview and its skeleton must share the preview radius.",
);
const detailPreviewRule = themeSource.match(
  /@media\s+screen\s*\{\s*\.app-shell--document \.resume-preview-card\s*\{([^}]+)\}/,
)?.[1];
assert(detailPreviewRule);
assert(
  /border:\s*0;/.test(detailPreviewRule) &&
    /border-radius:\s*0;/.test(detailPreviewRule) &&
    /background-color:\s*color-mix\(\s*in oklab,\s*var\(--muted\) 35%,\s*transparent\s*\);/.test(
      detailPreviewRule,
    ),
  "Document previews must use the muted workspace background without card borders.",
);

assert(
  /\.resume-page \{[\s\S]{0,320}border-radius: var\(--radius-md\);[\s\S]{0,120}border: 1px solid var\(--border\);[\s\S]{0,320}box-shadow:\s*var\(--surface-shadow-card\),\s*0 16px 40px -24px rgb\(9 9 11 \/ 0\.28\);/.test(
    themeSource,
  ) &&
    workspaceSkeletonsSource.includes(
      "rounded-md border border-border bg-background p-10 shadow-card",
    ),
  "A4 previews and their skeleton must share restrained paper chrome.",
);
const desktopPreviewRule = [
  ...themeSource.matchAll(
    /\.app-shell--document \.resume-preview-card\s*\{([^}]+)\}/g,
  ),
]
  .map((match) => match[1])
  .find((body) => /top:\s*calc\(/.test(body));
assert(desktopPreviewRule);
assert(
  /--document-sticky-top:\s*96px;/.test(themeSource) &&
    /--document-workspace-gutter:\s*16px;/.test(themeSource) &&
    /top:\s*calc\(\s*var\(--document-sticky-top\) - var\(--document-workspace-gutter\)\s*\);/.test(
      desktopPreviewRule,
    ) &&
    /height:\s*calc\(\s*100svh - var\(--document-sticky-top\) \+\s*var\(--document-workspace-gutter\)\s*\);/.test(
      desktopPreviewRule,
    ) &&
    /margin-top:\s*calc\(var\(--document-workspace-gutter\) \* -1\);/.test(
      desktopPreviewRule,
    ),
  "Desktop document canvases must meet the header and fill the available viewport height.",
);

assert(
  settingsWorkspacePageSource.includes("<SettingsPanelSkeleton />") &&
    settingsPanelSkeletonSource.includes("<SettingsSectionSkeleton") &&
    settingsPanelSkeletonSource.includes("<Card") &&
    settingsPanelSkeletonSource.includes("min-h-20") &&
    settingsPanelSkeletonSource.includes("py-4") &&
    settingsPanelSkeletonSource.includes("sm:min-h-16") &&
    settingsPanelSkeletonSource.includes("sm:py-3"),
  "Settings loading must preserve the live content-card hierarchy.",
);
assert(
  /data-slot="template-editor-skeleton"[\s\S]{0,120}className="min-h-\[520px\]"/.test(
    templateDetailWorkspaceViewSource,
  ) &&
    !/data-slot="template-editor-skeleton"[\s\S]{0,220}rounded-\(--radius-workspace\)/.test(
      templateDetailWorkspaceViewSource,
    ),
  "Template loading must preserve the cardless editor surface.",
);
for (const [name, source] of [
  ["resume gallery card", resumeGalleryCardSource],
  ["template gallery card", templateGalleryCardSource],
  ["gallery card skeleton", gallerySkeletonsSource],
]) {
  assert(
    source.includes("rounded-(--radius-card)") &&
      source.includes("shadow-card"),
    `The ${name} must use the shared content-card surface.`,
  );
}
for (const [name, source] of [
  ["resume gallery", resumeGallerySource],
  ["template gallery", templateGallerySource],
  ["recycle bin", recycleBinPanelSource],
]) {
  const workspaceClassName =
    source.match(/<section[\s\S]{0,120}?className="([^"]*)"/)?.[1] ?? "";
  assert(
    workspaceClassName.includes("rounded-(--radius-workspace)") &&
      workspaceClassName.includes("bg-muted/35") &&
      !/shadow-(?:card|xs|sm|md|lg|xl|2xl)|shadow-\[/.test(workspaceClassName),
    `The ${name} must use the shared flat workspace surface.`,
  );
}
assert(
  gallerySkeletonsSource.includes("h-full gap-0 rounded-(--radius-card)") &&
    gallerySkeletonsSource.includes("bg-card py-0"),
  "Gallery card skeletons must not inherit Card spacing around their content.",
);

for (const statusToken of ["success", "warning", "info"]) {
  assert(
    themeSource.includes(`--color-${statusToken}: var(--${statusToken});`) &&
      (themeSource.match(new RegExp(`^\\s*--${statusToken}:`, "gm")) ?? [])
        .length === 2,
    `The ${statusToken} status token must be mapped and defined for both themes.`,
  );
}
const statusComponentSource = [
  copilotChangeSummarySource,
  pdfExportRendererSource,
].join("\n");
assert(
  !/(?:text|bg|border)-(?:yellow|blue|green|orange|red|amber|emerald|sky|cyan|rose|lime|teal|indigo|violet)-\d+/.test(
    statusComponentSource,
  ),
  "Application status UI must use semantic status colors instead of palette utilities.",
);
assert(
  copilotChangeSummarySource.includes("text-warning") &&
    draftReviewComparisonSource.includes("bg-card") &&
    draftReviewComparisonSource.includes("text-card-foreground") &&
    draftReviewComparisonSource.includes("border-success/40"),
  "Agent review feedback must use semantic warning and success colors.",
);
assert(
  pdfExportRendererSource.includes("bg-background") &&
    pdfExportRendererSource.includes("text-destructive") &&
    !pdfExportRendererSource.includes("bg-white p-8 text-sm text-destructive"),
  "PDF export errors must keep semantic destructive contrast in dark mode.",
);
assert(
  selectSource.includes("border-input") &&
    selectSource.includes("dark:bg-input/30") &&
    selectSource.includes("data-[state=open]:animate-in"),
  "Select must retain the shadcn input and popover style contract.",
);
const selectContentPopperClassName =
  selectSource.match(
    /<SelectPrimitive\.Content[\s\S]*?position === "popper"\s*&&\s*"([^"]*)"[\s\S]*?position=\{position\}/,
  )?.[1] ?? "";
const selectContentPopperClasses = new Set(
  selectContentPopperClassName.split(/\s+/),
);
assert(
  selectContentPopperClasses.has("w-[var(--radix-select-trigger-width)]") &&
    selectContentPopperClasses.has("min-w-[var(--radix-select-trigger-width)]"),
  "Popper Select content must exactly match its trigger width.",
);

const toastStyleSource =
  appToasterSource.match(/style:\s*\{([\s\S]*?)\}\s*as CSSProperties/)?.[1] ??
  "";
let lastSemanticVariableIndex = -1;
for (const [toastType, token] of [
  ["success", "success"],
  ["warning", "warning"],
  ["info", "info"],
  ["error", "destructive"],
]) {
  for (const suffix of ["bg", "border", "text"]) {
    const variable = `--${toastType}-${suffix}`;
    const match = toastStyleSource.match(
      new RegExp(`"${variable}"\\s*:\\s*"([^"]+)"`),
    );
    assert(
      match?.[1].includes(`var(--${token})`),
      `AppToaster ${variable} must use the app ${token} token.`,
    );
    lastSemanticVariableIndex = Math.max(
      lastSemanticVariableIndex,
      match.index ?? -1,
    );
  }
}
assert(
  appToasterSource.includes("richColors") &&
    toastStyleSource.indexOf("...toastOptions?.style") >
      lastSemanticVariableIndex &&
    appToasterSource.includes("...toastOptions,") &&
    appToasterSource.includes("...toastOptions?.classNames,"),
  "AppToaster must merge semantic colors without discarding caller toast options.",
);

const toastActionClassName =
  appToasterSource.match(
    /actionButton:\s*cn\(\s*"([^"]*)",\s*toastOptions\?\.classNames\?\.actionButton/,
  )?.[1] ?? "";
for (const className of [
  "border-current/20!",
  "bg-transparent!",
  "text-current!",
  "hover:bg-current/10!",
  "focus-visible:ring-current!",
]) {
  assert(
    toastActionClassName.includes(className),
    `AppToaster action buttons must retain ${className}`,
  );
}

const smartOnePageToastOptions =
  resumeDetailCommandsSource.match(
    /toast\.success\(messages\.smartOnePageApplied,\s*\{([\s\S]*?)\n\s*\}\);/,
  )?.[1] ?? "";
assert(
  smartOnePageToastOptions.includes("duration: 6_000"),
  "Fit-to-one-page undo must remain available for six seconds.",
);

console.log("shadcn theme contract verified.");
