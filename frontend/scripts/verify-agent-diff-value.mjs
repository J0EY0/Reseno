import assert from "node:assert/strict";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const server = await createServer({
  cacheDir: createViteTestCacheDir("agent-diff-value"),
  configFile: false,
  logLevel: "error",
  optimizeDeps: { noDiscovery: true },
  root: process.cwd(),
  server: { hmr: false, middlewareMode: true, ws: false },
  resolve: {
    alias: { "@": new URL("../src", import.meta.url).pathname },
  },
});

try {
  const { formatAgentDiffValue, getAgentEditDiff } = await server.ssrLoadModule(
    "/src/lib/agent-diff-value.ts",
  );
  const value = formatAgentDiffValue({
    id: "project-1",
    name: "ResuMate",
    role: "Frontend engineer",
    techStack: ["React", "TypeScript", "Tailwind CSS"],
    period: "2025–2026",
    url: "https://example.com",
    description: "AI resume workspace",
    highlights: ["Built the editor", "Added agent workflows"],
  });

  for (const expected of [
    "ResuMate",
    "Frontend engineer",
    "React",
    "TypeScript",
    "Tailwind CSS",
    "2025–2026",
    "https://example.com",
    "AI resume workspace",
    "Built the editor",
    "Added agent workflows",
  ]) {
    assert.match(value, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.doesNotMatch(value, /project-1/);
  assert.match(formatAgentDiffValue({ content: "English · CET-6" }), /English · CET-6/);
  assert.equal(formatAgentDiffValue(""), "—");
  assert.equal(formatAgentDiffValue([]), "—");
  assert.match(formatAgentDiffValue({ highlights: [] }), /highlights: —/);
  assert.match(formatAgentDiffValue({ description: "" }), /description: —/);

  const sameTargetEdits = [
    {
      id: "edit-summary-1",
      title: "First summary edit",
      target: "basic.summary",
      reason: "First step",
      diffs: [{
        id: "diff-summary-1",
        operationId: "edit-summary-1",
        path: "basic.summary",
        kind: "modified",
        label: "Summary",
        before: "A",
        after: "B",
      }],
    },
    {
      id: "edit-summary-2",
      title: "Second summary edit",
      target: "basic.summary",
      reason: "Second step",
      diffs: [{
        id: "diff-summary-2",
        operationId: "edit-summary-2",
        path: "basic.summary",
        kind: "modified",
        label: "Summary",
        before: "B",
        after: "C",
      }],
    },
  ];
  assert.deepEqual(getAgentEditDiff(sameTargetEdits[0]), {
    before: "A",
    after: "B",
  });
  assert.deepEqual(getAgentEditDiff(sameTargetEdits[1]), {
    before: "B",
    after: "C",
  });
} finally {
  await server.close();
}

console.log("Agent draft diff value checks passed.");
