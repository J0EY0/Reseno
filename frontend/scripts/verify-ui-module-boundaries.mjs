import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
import {
  findCalls,
  findNodes,
  hasImport,
  parseSource,
} from "./source-analysis.mjs";

const srcRoot = new URL("../src/", import.meta.url);
const files = new Map();
async function source(path) {
  if (!files.has(path))
    files.set(
      path,
      parseSource(await readFile(new URL(path, srcRoot), "utf8"), path),
    );
  return files.get(path);
}
for (const [entry, dependencies] of [
  ["components/ui/sidebar.tsx", ["@/components/ui/sidebar-state"]],
  ["components/ui/sidebar-layout.tsx", ["@/components/ui/sidebar"]],
  ["components/ui/sidebar-menu.tsx", ["@/components/ui/sidebar"]],
  [
    "components/app-sidebar.tsx",
    ["@/components/ui/sidebar-layout", "@/components/ui/sidebar-menu"],
  ],
  [
    "components/editor/avatar-crop-dialog.tsx",
    ["./use-avatar-crop", "./avatar-crop-dialog-view"],
  ],
  ["components/editor/use-avatar-crop.ts", ["@/lib/avatar"]],
  ["components/editor/avatar-crop-canvas.tsx", ["./avatar-crop-geometry"]],
  ["components/save-status-button.tsx", ["@/components/ui/popover"]],
  [
    "components/resume-gallery.tsx",
    [
      "@/components/resume-gallery-grid",
      "@/components/use-resume-gallery-controller",
    ],
  ],
  [
    "components/templates/template-gallery.tsx",
    ["./template-gallery-grid", "./use-template-gallery-controller"],
  ],
  [
    "components/resume-gallery-card.tsx",
    ["@/components/preview/resume-thumbnail"],
  ],
  [
    "components/templates/template-gallery-card.tsx",
    ["@/components/preview/resume-thumbnail"],
  ],
]) {
  for (const dependency of dependencies)
    assert.ok(
      hasImport(await source(entry), dependency),
      `${entry} must retain its ${dependency} boundary.`,
    );
}
for (const [entry, forbidden] of [
  ["components/ui/sidebar.tsx", ["SidebarMenuButton", "SidebarGroupLabel"]],
  [
    "components/save-status-button.tsx",
    ["HoverCard", "HoverCardContent", "HoverCardTrigger"],
  ],
  ["components/resume-gallery-grid.tsx", ["Empty"]],
  ["components/templates/template-gallery-grid.tsx", ["Empty"]],
]) {
  const identifiers = findNodes(await source(entry), ts.isIdentifier).map(
    (node) => node.text,
  );
  for (const name of forbidden)
    assert.ok(!identifiers.includes(name), `${entry} must not absorb ${name}.`);
  assert.ok(
    !(await source(entry)).statements.some(ts.isExportDeclaration),
    `${entry} must not become a compatibility barrel.`,
  );
}
for (const entry of [
  "components/resume-gallery-card.tsx",
  "components/templates/template-gallery-card.tsx",
]) {
  assert.ok(
    findCalls(await source(entry), "memo").length > 0,
    `${entry} must retain its memoized preview boundary.`,
  );
}
for (const entry of [
  "components/use-resume-gallery-controller.ts",
  "components/templates/use-template-gallery-controller.ts",
]) {
  assert.ok(
    findCalls(await source(entry), "useDeferredValue").length > 0,
    `${entry} must defer gallery filtering in its controller.`,
  );
}
console.log(
  "Sidebar, gallery, and avatar crop dependency boundaries verified.",
);
