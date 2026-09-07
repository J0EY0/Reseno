import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
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
  const {
    compactResumeDraftDiffs,
    formatAgentDiffValue,
  } = await server.ssrLoadModule("/src/lib/agent-diff-value.ts");
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
  assert.equal(
    formatAgentDiffValue("Use <Component> here; do not rewrite it."),
    "Use <Component> here; do not rewrite it.",
    "Ordinary text containing angle brackets must not be treated as rich text.",
  );
  assert.equal(
    formatAgentDiffValue("Explain the literal <strong>text</strong> markup to the user."),
    "Explain the literal <strong>text</strong> markup to the user.",
    "Inline markup mentioned inside ordinary text must remain literal text.",
  );
  assert.equal(
    formatAgentDiffValue("<p>literal but mismatched</strong>"),
    "<p>literal but mismatched</strong>",
    "Mismatched markup must not be mistaken for a canonical rich-text document.",
  );
  assert.equal(
    formatAgentDiffValue("<ol><li>First</li><li>Second</li></ol>"),
    "1. First\n2. Second",
    "Rich-list presentation must be derived from document shape, not a field name.",
  );
  assert.equal(
    formatAgentDiffValue("<ul><li>R&amp;D &lt;AI&gt;</li></ul>"),
    "• R&D <AI>",
    "Stored HTML entities must be presented as their visible characters.",
  );
  assert.equal(
    formatAgentDiffValue("<p>&#39;single&#x27; &#160;space</p>"),
    "'single' space",
    "Decimal and hexadecimal entities emitted by canonical serializers must be decoded.",
  );
  assert.equal(
    formatAgentDiffValue("<p><strong>React</strong> and <em>TypeScript</em></p>"),
    "React and TypeScript",
    "Canonical paragraph and inline formatting tags must not leak into the summary.",
  );
  assert.equal(
    formatAgentDiffValue("<div>Intro<p>Alpha</p><p>Beta</p></div>"),
    "Intro\nAlpha\nBeta",
    "Adjacent canonical blocks must preserve their visible line boundaries.",
  );
  assert.equal(
    formatAgentDiffValue(
      "<ul><li>Frontend<ul><li>React</li><li>TypeScript</li></ul></li><li>Backend</li></ul>",
    ),
    "• Frontend\n  • React\n  • TypeScript\n• Backend",
    "Nested canonical lists must remain readable without exposing their tags.",
  );
  assert.equal(
    formatAgentDiffValue(["<ul></ul>"]),
    "—",
    "An empty rich-text document must use the existing empty-value presentation.",
  );
  assert.equal(
    formatAgentDiffValue(["<ul><li>React</li><li>TypeScript</li></ul>"]),
    "• React\n• TypeScript",
    "A rich list nested in a collection must not gain duplicate bullet prefixes.",
  );
  assert.equal(
    formatAgentDiffValue(["<p>React</p>", "TypeScript"]),
    "• React\n• TypeScript",
    "Rich paragraphs and plain strings in one collection must share the same markers.",
  );
  const nestedRichValue = {
    arbitraryPayload: "<ul><li>Visible value</li></ul>",
  };
  const nestedRichSnapshot = structuredClone(nestedRichValue);
  assert.match(
    formatAgentDiffValue(nestedRichValue),
    /arbitraryPayload: • Visible value/,
  );
  assert.deepEqual(
    nestedRichValue,
    nestedRichSnapshot,
    "Formatting a diff value must not mutate its canonical data.",
  );
  const unsafeRichValue = formatAgentDiffValue(
    '<ul><li><img src="x" onerror="alert(1)"><svg/onload=alert(2)><!--hidden-->Visible<script>alert(3)</script></li></ul>',
  );
  assert.doesNotMatch(unsafeRichValue, /<img|<svg|onerror|<!--|<script/i);
  assert.match(unsafeRichValue, /Visible/);

  const sameTargetEdits = [
    {
      id: "edit-summary-1",
      title: "First summary edit",
      target: "basic.summary",
      reason: "First step",
      operation: { type: "replace_field", path: "basic.summary", value: "B" },
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
      operation: { type: "replace_field", path: "basic.summary", value: "C" },
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

  const multiFieldEdit = {
    id: "edit-project-1",
    title: "Refine project",
    target: "sections.project.items.project-1",
    reason: "Make the project more concise",
    operation: {
      type: "update_item",
      sectionId: "project",
      itemId: "project-1",
      patch: {
        description: "Built an AI resume editor with live preview.",
        highlights: ["Reduced state complexity"],
      },
    },
    diffs: [
      {
        id: "agent-diff-edit-project-1-description",
        operationId: "edit-project-1",
        path: "sections.project.items.project-1.description",
        kind: "modified",
        label: "Project Description",
        sectionId: "project",
        itemId: "project-1",
        before: "Built an AI resume editor with real-time preview.",
        after: "Built an AI resume editor with live preview.",
      },
      {
        id: "agent-diff-edit-project-1-highlights",
        operationId: "edit-project-1",
        path: "sections.project.items.project-1.highlights",
        kind: "modified",
        label: "Project Highlights",
        sectionId: "project",
        itemId: "project-1",
        before: ["Reduced state complexity", "Improved interaction details"],
        after: ["Reduced state complexity"],
      },
      {
        id: "agent-diff-edit-project-1-period",
        operationId: "edit-project-1",
        path: "sections.project.items.project-1.period",
        kind: "modified",
        label: "Project Period",
        sectionId: "project",
        itemId: "project-1",
        before: "2026.03 - present",
        after: "2026.03 - present",
      },
    ],
  };

  const { AgentChangeSummary } = await server.ssrLoadModule(
    "/src/components/copilot/copilot-change-summary.tsx",
  );
  const renderSummary = (reviewItems, tools = []) =>
    renderToStaticMarkup(
      createElement(AgentChangeSummary, {
        response: {
          id: "assistant-1",
          role: "assistant",
          text: "Updated the resume.",
          transactionState: "committed",
          edits: [multiFieldEdit],
          tools,
          draft: {
            baseResume: {},
            reviewItems,
          },
        },
        t: {
          agentDraftResolutionReceipt:
            "Applied {applied}, discarded {discarded}",
          agentQualityDuplicateContent: "Duplicate content",
          agentQualityGeneral: "Review this suggestion",
          agentQualityInconsistentTense: "Inconsistent tense",
          agentQualityMixedLanguages: "Mixed languages",
          agentQualityReverseChronology: "Chronology",
          agentQualityTargetCoverage: "Target coverage",
          agentQualityUnsupportedClaim: "Unsupported claim",
          agentQualityWarnings: "{count} warnings",
        },
      }),
    );
  const pendingMarkup = renderSummary([
    { id: "review-1", editIds: [multiFieldEdit.id], status: "pending" },
  ]);
  assert.equal(
    pendingMarkup,
    "",
    "Pending review controls belong to the composer dock, not message history.",
  );
  const receiptMarkup = renderSummary([
    { id: "review-1", editIds: ["edit-1"], status: "applied" },
    { id: "review-2", editIds: ["edit-2"], status: "applied" },
    { id: "review-3", editIds: ["edit-3"], status: "discarded" },
  ]);
  assert.match(receiptMarkup, /data-slot="agent-draft-resolution-receipt"/);
  assert.match(receiptMarkup, /Applied 2, discarded 1/);
  assert.doesNotMatch(receiptMarkup, /Apply draft|Discard draft|role="group"/);
  const warningMarkup = renderSummary(
    [{ id: "review-1", editIds: ["edit-1"], status: "pending" }],
    [{
      state: "output-available",
      output: {
        qualityIssues: [
          {
            code: "target_requirements_not_covered",
            severity: "warning",
            target: "resume",
          },
          {
            code: "unsupported_edit_claim",
            severity: "warning",
            target: "sections.project.items.project-1",
          },
        ],
      },
    }],
  );
  assert.match(warningMarkup, /2 warnings/);
  assert.match(warningMarkup, /Target coverage/);
  assert.match(warningMarkup, /Unsupported claim/);
  assert.doesNotMatch(warningMarkup, /target_requirements_not_covered/);

  const { AgentDraftReviewDock } = await server.ssrLoadModule(
    "/src/components/copilot/agent-draft-review-dock.tsx",
  );
  const dockMessages = {
    agentApplyRemaining: "Apply remaining",
    agentApplyThis: "Apply this change",
    agentApplyingDraft: "Applying change",
    agentDiscardRemaining: "Discard remaining",
    agentDiscardThis: "Discard this change",
    agentDiscardingDraft: "Discarding change",
    agentDraftReview: "Draft change review",
    agentReviewAll: "All",
    agentReviewNext: "Next change",
    agentReviewOneByOne: "Review one by one",
    agentReviewPrevious: "Previous change",
    agentReviewRemaining: "{count} remaining",
    agentReviewSingleMode: "Single preview",
    agentReviewSinglePosition: "{current} of {total}",
  };
  const dockActions = {
    onApply: () => undefined,
    onDiscard: () => undefined,
    onNext: () => undefined,
    onPrevious: () => undefined,
    onSelectFirst: () => undefined,
    onShowAll: () => undefined,
  };
  const allDockMarkup = renderToStaticMarkup(
    createElement(AgentDraftReviewDock, {
      t: dockMessages,
      view: {
        ...dockActions,
        disabled: false,
        mode: "all",
        pendingCount: 5,
        resolvingStatus: null,
        selectedIndex: -1,
      },
    }),
  );
  assert.match(allDockMarkup, /5 remaining/);
  assert.match(allDockMarkup, /data-orientation="horizontal"/);
  assert.match(allDockMarkup, /Apply remaining/);
  assert.match(allDockMarkup, /Discard remaining/);
  assert.match(allDockMarkup, /aria-label="Review one by one"/);
  assert.doesNotMatch(allDockMarkup, /data-variant="(?:default|outline)"/);

  const singleDockMarkup = renderToStaticMarkup(
    createElement(AgentDraftReviewDock, {
      t: dockMessages,
      view: {
        ...dockActions,
        disabled: false,
        mode: "single",
        pendingCount: 4,
        resolvingStatus: "applied",
        selectedIndex: 1,
      },
    }),
  );
  assert.match(singleDockMarkup, /2 of 4/);
  assert.match(singleDockMarkup, /Single preview/);
  assert.match(singleDockMarkup, /Apply this change/);
  assert.match(singleDockMarkup, /Discard this change/);
  assert.match(singleDockMarkup, /aria-label="Applying change"/);
  assert.match(singleDockMarkup, /disabled=""/);

  const revertedEdits = [
    sameTargetEdits[0],
    {
      ...sameTargetEdits[1],
      diffs: [{
        ...sameTargetEdits[1].diffs[0],
        after: "A",
      }],
    },
  ];
  assert.deepEqual(
    compactResumeDraftDiffs(revertedEdits.flatMap((edit) => edit.diffs)),
    [],
    "A field restored to its original value must not remain a pending change.",
  );

  const insertedProject = {
    id: "project-new",
    name: "ResuMate",
    description: "Initial description",
    highlights: [],
  };
  const updatedProject = {
    ...insertedProject,
    description: "Updated description",
  };
  assert.deepEqual(
    compactResumeDraftDiffs([
      {
        id: "diff-insert-project",
        operationId: "edit-insert-project",
        path: "sections.project.items.project-new",
        kind: "added",
        label: "Add project",
        sectionId: "project",
        itemId: "project-new",
        after: insertedProject,
      },
      {
        id: "diff-update-project-description",
        operationId: "edit-update-project",
        path: "sections.project.items.project-new.description",
        kind: "modified",
        label: "Update project",
        sectionId: "project",
        itemId: "project-new",
        before: "Initial description",
        after: "Updated description",
      },
      {
        id: "diff-delete-project",
        operationId: "edit-delete-project",
        path: "sections.project.items.project-new",
        kind: "deleted",
        label: "Delete project",
        sectionId: "project",
        itemId: "project-new",
        before: updatedProject,
      },
    ]),
    [],
    "An item inserted and then deleted in the same draft must leave no net diff.",
  );

  const originalProject = {
    id: "project-existing",
    name: "Existing project",
    description: "Original description",
    highlights: [],
  };
  const revisedProject = {
    ...originalProject,
    description: "Revised description",
  };
  assert.deepEqual(
    compactResumeDraftDiffs([
      {
        id: "diff-revise-existing-description",
        operationId: "edit-revise-existing",
        path: "sections.project.items.project-existing.description",
        kind: "modified",
        label: "Revise existing project",
        sectionId: "project",
        itemId: "project-existing",
        before: "Original description",
        after: "Revised description",
      },
      {
        id: "diff-delete-existing-project",
        operationId: "edit-delete-existing",
        path: "sections.project.items.project-existing",
        kind: "deleted",
        label: "Delete existing project",
        sectionId: "project",
        itemId: "project-existing",
        before: revisedProject,
      },
    ]),
    [
      {
        id: "diff-delete-existing-project",
        operationId: "edit-delete-existing",
        path: "sections.project.items.project-existing",
        kind: "deleted",
        label: "Delete existing project",
        sectionId: "project",
        itemId: "project-existing",
        before: originalProject,
      },
    ],
    "Deleting an existing item must retain one parent diff with its original baseline.",
  );

  assert.deepEqual(
    compactResumeDraftDiffs([
      {
        id: "diff-add-then-update-project",
        operationId: "edit-add-then-update-project",
        path: "sections.project.items.project-new",
        kind: "added",
        label: "Add project",
        sectionId: "project",
        itemId: "project-new",
        after: insertedProject,
      },
      {
        id: "diff-update-added-project-description",
        operationId: "edit-update-added-project",
        path: "sections.project.items.project-new.description",
        kind: "modified",
        label: "Update added project",
        sectionId: "project",
        itemId: "project-new",
        before: "Initial description",
        after: "Updated description",
      },
    ]),
    [
      {
        id: "diff-add-then-update-project",
        operationId: "edit-add-then-update-project",
        path: "sections.project.items.project-new",
        kind: "added",
        label: "Add project",
        sectionId: "project",
        itemId: "project-new",
        after: updatedProject,
      },
    ],
    "Updating an inserted item must keep one added diff with the final snapshot.",
  );

  const originalExperience = {
    id: "experience-existing",
    kind: "experience",
    title: "Experience",
    items: [{
      id: "job-existing",
      company: "Acme",
      position: "Engineer",
      location: "Remote",
      period: "2024–2026",
      description: "Original description",
      highlights: [],
    }],
  };
  const revisedExperience = {
    ...originalExperience,
    items: [{
      ...originalExperience.items[0],
      description: "Revised description",
    }],
  };
  assert.deepEqual(
    compactResumeDraftDiffs([
      {
        id: "diff-revise-experience-item",
        operationId: "edit-revise-experience-item",
        path: "sections.experience-existing.items.job-existing.description",
        kind: "modified",
        label: "Experience Description",
        sectionId: "experience-existing",
        itemId: "job-existing",
        before: "Original description",
        after: "Revised description",
      },
      {
        id: "diff-delete-experience-section",
        operationId: "edit-delete-experience-section",
        path: "sections.experience-existing",
        kind: "deleted",
        label: "Delete experience section",
        sectionId: "experience-existing",
        before: revisedExperience,
      },
    ]),
    [{
      id: "diff-delete-experience-section",
      operationId: "edit-delete-experience-section",
      path: "sections.experience-existing",
      kind: "deleted",
      label: "Delete experience section",
      sectionId: "experience-existing",
      before: originalExperience,
    }],
    "Deleting a section must rewind item field changes inside its items array.",
  );

  const addedExperience = {
    ...originalExperience,
    id: "experience-new",
    items: [{
      ...originalExperience.items[0],
      id: "job-new",
    }],
  };
  const updatedAddedExperience = {
    ...addedExperience,
    items: [{
      ...addedExperience.items[0],
      description: "Updated after insertion",
    }],
  };
  assert.deepEqual(
    compactResumeDraftDiffs([
      {
        id: "diff-add-experience-section",
        operationId: "edit-add-experience-section",
        path: "sections.experience-new",
        kind: "added",
        label: "Add experience section",
        sectionId: "experience-new",
        after: addedExperience,
      },
      {
        id: "diff-update-added-experience-item",
        operationId: "edit-update-added-experience-item",
        path: "sections.experience-new.items.job-new.description",
        kind: "modified",
        label: "Experience Description",
        sectionId: "experience-new",
        itemId: "job-new",
        before: "Original description",
        after: "Updated after insertion",
      },
    ]),
    [{
      id: "diff-add-experience-section",
      operationId: "edit-add-experience-section",
      path: "sections.experience-new",
      kind: "added",
      label: "Add experience section",
      sectionId: "experience-new",
      after: updatedAddedExperience,
    }],
    "Updating an item in an inserted section must keep one final section snapshot.",
  );

  const originalReorderSection = {
    id: "experience-reorder",
    kind: "experience",
    title: "Experience",
    items: [
      { ...originalExperience.items[0], id: "job-a", company: "Alpha" },
      { ...originalExperience.items[0], id: "job-b", company: "Beta" },
    ],
  };
  const reorderedSection = {
    ...originalReorderSection,
    items: [
      originalReorderSection.items[1],
      originalReorderSection.items[0],
    ],
  };
  assert.deepEqual(
    compactResumeDraftDiffs([
      {
        id: "diff-reorder-experience-items",
        operationId: "edit-reorder-experience-items",
        path: "sections.experience-reorder.items",
        kind: "moved",
        label: "Reorder experience items",
        sectionId: "experience-reorder",
        before: ["job-a", "job-b"],
        after: ["job-b", "job-a"],
      },
      {
        id: "diff-delete-reordered-section",
        operationId: "edit-delete-reordered-section",
        path: "sections.experience-reorder",
        kind: "deleted",
        label: "Delete experience section",
        sectionId: "experience-reorder",
        before: reorderedSection,
      },
    ]),
    [{
      id: "diff-delete-reordered-section",
      operationId: "edit-delete-reordered-section",
      path: "sections.experience-reorder",
      kind: "deleted",
      label: "Delete experience section",
      sectionId: "experience-reorder",
      before: originalReorderSection,
    }],
    "Rewinding a reorder must preserve item objects in the deleted section snapshot.",
  );

  const dottedSection = {
    ...addedExperience,
    id: "experience.archive",
    items: [{
      ...addedExperience.items[0],
      id: "job.v2",
    }],
  };
  const updatedDottedSection = {
    ...dottedSection,
    items: [{
      ...dottedSection.items[0],
      description: "Updated dotted item",
    }],
  };
  assert.deepEqual(
    compactResumeDraftDiffs([
      {
        id: "diff-add-dotted-section",
        operationId: "edit-add-dotted-section",
        path: "sections.experience.archive",
        kind: "added",
        label: "Add archived experience",
        sectionId: "experience.archive",
        after: dottedSection,
      },
      {
        id: "diff-update-dotted-item",
        operationId: "edit-update-dotted-item",
        path: "sections.experience.archive.items.job.v2.description",
        kind: "modified",
        label: "Experience Description",
        sectionId: "experience.archive",
        itemId: "job.v2",
        before: "Original description",
        after: "Updated dotted item",
      },
    ]),
    [{
      id: "diff-add-dotted-section",
      operationId: "edit-add-dotted-section",
      path: "sections.experience.archive",
      kind: "added",
      label: "Add archived experience",
      sectionId: "experience.archive",
      after: updatedDottedSection,
    }],
    "Section and item IDs containing dots must remain atomic path segments.",
  );

  const collidingSection = {
    ...originalExperience,
    id: "team.items.role",
    items: [],
  };
  const collidingItem = {
    ...originalExperience.items[0],
    id: "role",
  };
  assert.deepEqual(
    compactResumeDraftDiffs([
      {
        id: "diff-add-colliding-section",
        operationId: "edit-add-colliding-section",
        path: "sections.team.items.role",
        kind: "added",
        label: "Add colliding section",
        sectionId: "team.items.role",
        after: collidingSection,
      },
      {
        id: "diff-add-colliding-item",
        operationId: "edit-add-colliding-item",
        path: "sections.team.items.role",
        kind: "added",
        label: "Add colliding item",
        sectionId: "team",
        itemId: "role",
        after: collidingItem,
      },
    ]),
    [
      {
        id: "diff-add-colliding-section",
        operationId: "edit-add-colliding-section",
        path: "sections.team.items.role",
        kind: "added",
        label: "Add colliding section",
        sectionId: "team.items.role",
        after: collidingSection,
      },
      {
        id: "diff-add-colliding-item",
        operationId: "edit-add-colliding-item",
        path: "sections.team.items.role",
        kind: "added",
        label: "Add colliding item",
        sectionId: "team",
        itemId: "role",
        after: collidingItem,
      },
    ],
    "Distinct canonical targets must not collide when their serialized paths match.",
  );
} finally {
  await server.close();
}

console.log("Agent draft diff value checks passed.");
