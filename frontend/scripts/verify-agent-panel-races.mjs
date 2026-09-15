import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
import { findNodes, parseSource } from "./source-analysis.mjs";

const [
  panelSource,
  panelTypesSource,
  agentHostSource,
  agentLayoutSource,
  workspaceViewSource,
  workspaceColumnsSource,
  workspaceColumnsStylesSource,
  agentMotionStylesSource,
  appStylesSource,
] = await Promise.all(
  [
    "components/copilot/copilot-panel.tsx",
    "components/copilot/copilot-panel-types.ts",
    "components/workspace/resume-detail-agent-host.tsx",
    "components/workspace/use-resume-detail-agent-layout.ts",
    "components/workspace/resume-detail-workspace-view.tsx",
    "components/workspace/resume-workspace-columns.tsx",
    "components/workspace/resume-workspace-columns.css",
    "components/workspace/resume-detail-agent-motion.css",
    "index.css",
  ].map((path) => readFile(new URL(`../src/${path}`, import.meta.url), "utf8")),
);

const desktopWorkspaceGridRule =
  workspaceColumnsStylesSource.match(
    /@media\s*\(min-width:\s*1280px\)\s*\{[\s\S]*?\n\s*\.resume-workspace\s*\{([^}]*)\}/,
  )?.[1] ?? "";
const panelMotionRule =
  agentMotionStylesSource.match(
    /\.app-shell--document\s+\.agent-panel-motion-layer\s*\{([^}]*)\}/,
  )?.[1] ?? "";
const hiddenPanelMotionRule =
  agentMotionStylesSource.match(
    /\.agent-panel-dock\[aria-hidden=["']true["']\]\s+\.agent-panel-motion-layer\s*\{([^}]*)\}/,
  )?.[1] ?? "";

assert(
  ([appStylesSource, workspaceColumnsStylesSource, agentMotionStylesSource]
    .join("\n")
    .match(/transition(?:-property)?\s*:[^;{}]*\bgrid-template-columns\b/g)
    ?.length ?? 0) === 1 &&
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
  workspaceColumnsSource.includes('import "./resume-workspace-columns.css";') &&
    workspaceColumnsSource.includes(
      '"--agent-panel-width": `${agentWidth}px`',
    ) &&
    workspaceColumnsSource.includes("resolveWorkspaceWidths("),
  "The desktop Agent motion layer must keep its resolved width while the grid track clips it.",
);

assert(
  findNodes(parseSource(agentHostSource), ts.isStringLiteral).some(
    (node) =>
      node.text.split(/\s+/).includes("agent-panel-dock") &&
      node.text.split(/\s+/).includes("overflow-hidden"),
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
  /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*\*,\s*\*::before,\s*\*::after\s*\{[^}]*transition:\s*none\s*!important/.test(
    appStylesSource,
  ),
  "Reduced-motion users must not receive workspace or panel transitions.",
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
  workspaceViewSource.includes("<ResumeWorkspaceColumns") &&
    workspaceViewSource.includes(
      "agentExpanded={!state.agent.isPanelCollapsed}",
    ) &&
    workspaceViewSource.includes("<ResumeDetailAgentToggle") &&
    workspaceViewSource.includes("toolbarTrailing={") &&
    workspaceColumnsSource.includes(
      '"--resume-workspace-columns": `var(--editor-panel-width) minmax(${PREVIEW_MIN_WIDTH}px,1fr)',
    ) &&
    workspaceColumnsSource.includes(
      'agentExpanded ? "var(--agent-panel-width)" : "0px"',
    ) &&
    /@media \(min-width: 1280px\) \{[\s\S]{0,2400}\.resume-workspace\s*\{[\s\S]{0,400}grid-template-columns:\s*var\(\s*--resume-workspace-columns/.test(
      workspaceColumnsStylesSource,
    ),
  "Desktop layouts must compose the editor, canvas, and inline Agent as three tracks with the toggle inside the canvas toolbar.",
);

assert(
  appStylesSource.includes("grid-template-columns: minmax(0, 1fr);") &&
    workspaceColumnsStylesSource.includes(
      ".resume-workspace > .workspace-agent-column {\n    grid-column: 1;\n    grid-row: 2;",
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

console.log("Agent layout architecture checks passed.");
