import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const frontendRoot = new URL("../", import.meta.url);
const readText = (path) => readFile(new URL(path, frontendRoot), "utf8");

const sources = new Map(
  await Promise.all(
    [
      "src/components/deleted-resume-trash-list.tsx",
      "src/components/deleted-template-trash-list.tsx",
      "src/components/gallery-pagination.tsx",
      "src/components/preview/document-preview-card.tsx",
      "src/components/resume-gallery-card.tsx",
      "src/components/templates/template-gallery-card.tsx",
      "src/components/workspace/resume-detail-workspace-header.tsx",
      "src/components/workspace/resume-detail-workspace-view.tsx",
      "src/components/workspace/template-detail-workspace-header.tsx",
      "src/components/workspace/template-detail-workspace-view.tsx",
      "src/components/workspace/use-prepared-workspace-navigation.ts",
      "src/components/workspace/use-resume-detail-workspace.ts",
      "src/components/workspace/use-resume-gallery-workspace.ts",
      "src/components/workspace/use-template-detail-workspace.ts",
      "src/components/workspace/use-template-gallery-workspace.ts",
      "src/hooks/use-auth-gate.ts",
    ].map(async (path) => [path, await readText(path)]),
  ),
);

for (const [path, source] of sources) {
  assert.doesNotMatch(
    source,
    /ViewTransitionBoundary|runViewTransition|viewTransitionName|@\/components\/view-transition|@\/lib\/view-transition/,
    `${path} must not retain the unavailable React ViewTransition path.`,
  );
}

for (const path of [
  "src/components/gallery-pagination.tsx",
  "src/components/workspace/use-prepared-workspace-navigation.ts",
  "src/components/workspace/use-resume-detail-workspace.ts",
  "src/components/workspace/use-resume-gallery-workspace.ts",
  "src/components/workspace/use-template-detail-workspace.ts",
  "src/components/workspace/use-template-gallery-workspace.ts",
  "src/hooks/use-auth-gate.ts",
]) {
  assert.match(
    sources.get(path),
    /\bstartTransition\s*\(/,
    `${path} must preserve non-urgent commits with React startTransition.`,
  );
}

for (const path of [
  "src/components/workspace/resume-detail-workspace-view.tsx",
  "src/components/workspace/template-detail-workspace-view.tsx",
]) {
  assert.match(
    sources.get(path),
    /workspace-document-enter/,
    `${path} must expose the ordinary DOM document-entry motion hook.`,
  );
}

console.log("Unavailable non-gallery ViewTransition paths removed.");
