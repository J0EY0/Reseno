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
    getAgentEditDiffFields,
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
  assert.deepEqual(getAgentEditDiffFields(sameTargetEdits[0]), [
    {
      id: "diff-summary-1",
      label: "Summary",
      before: "A",
      after: "B",
    },
  ]);
  assert.deepEqual(getAgentEditDiffFields(sameTargetEdits[1]), [
    {
      id: "diff-summary-2",
      label: "Summary",
      before: "B",
      after: "C",
    },
  ]);

  const multiFieldEdit = {
    id: "edit-project-1",
    title: "Refine project",
    target: "sections.project.items.project-1",
    reason: "Make the project more concise",
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
  assert.deepEqual(getAgentEditDiffFields(multiFieldEdit), [
    {
      id: "agent-diff-edit-project-1-description",
      label: "Project Description",
      before: "Built an AI resume editor with real-time preview.",
      after: "Built an AI resume editor with live preview.",
    },
    {
      id: "agent-diff-edit-project-1-highlights",
      label: "Project Highlights",
      before: "• Reduced state complexity\n• Improved interaction details",
      after: "• Reduced state complexity",
    },
  ]);

  const { AgentChangeSummary } = await server.ssrLoadModule(
    "/src/components/copilot/copilot-change-summary.tsx",
  );
  const renderSummary = (edits, draftDiffs, tools = []) =>
    renderToStaticMarkup(
      createElement(AgentChangeSummary, {
        draftDiffs,
        hasAgentDraft: false,
        onApplyAgentDraft: () => undefined,
        onDiscardAgentDraft: () => undefined,
        response: {
          id: "assistant-1",
          role: "assistant",
          text: "Updated the resume.",
          transactionState: "committed",
          edits,
          tools,
        },
        shouldShowDraftActions: false,
        t: {
          agentApplyDraft: "Apply",
          agentChangeSummaryTitle: "Change summary",
          agentDiffAfter: "After",
          agentDiffBefore: "Before",
          agentDiscardDraft: "Discard",
          agentDraftSynced: "Draft synced",
          agentQualityDuplicateContent: "Duplicate content",
          agentQualityGeneral: "Review this suggestion",
          agentQualityInconsistentTense: "Inconsistent tense",
          agentQualityMixedLanguages: "Mixed languages",
          agentQualityReverseChronology: "Chronology",
          agentQualityTargetCoverage: "Target coverage",
          agentQualityUnsupportedClaim: "Unsupported claim",
          agentQualityWarnings: "{count} warnings",
          agentReviewReady: "{count} changes ready",
        },
      }),
    );
  const summaryMarkup = renderSummary([multiFieldEdit]);
  assert.match(summaryMarkup, />Refine project</);
  assert.match(summaryMarkup, /role="group"/);
  assert.match(summaryMarkup, /aria-label="Project Description"/);
  assert.match(summaryMarkup, /aria-label="Project Highlights"/);
  assert.doesNotMatch(summaryMarkup, />Project Description</);
  assert.doesNotMatch(summaryMarkup, />Project Highlights</);
  assert.doesNotMatch(summaryMarkup, /aria-label="Project Period"/);
  assert.match(summaryMarkup, /2 changes ready/);
  assert.match(summaryMarkup, /Built an AI resume editor with real-time preview\./);
  assert.match(summaryMarkup, /Reduced state complexity/);

  const warningMarkup = renderSummary([multiFieldEdit], undefined, [
    {
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
    },
  ]);
  assert.match(warningMarkup, /2 warnings/);
  assert.match(warningMarkup, /Target coverage/);
  assert.match(warningMarkup, /Unsupported claim/);
  assert.doesNotMatch(warningMarkup, /target_requirements_not_covered/);
  assert.doesNotMatch(warningMarkup, /sections\.project/);

  const richListEdit = {
    id: "edit-skills-list",
    title: "Group related skills",
    target: "sections.skills.items.skills-list.content",
    reason: "Make the skills easier to scan",
    diffs: [{
      id: "diff-skills-list-content",
      operationId: "edit-skills-list",
      path: "sections.skills.items.skills-list.content",
      kind: "modified",
      label: "Skills",
      sectionId: "skills",
      itemId: "skills-list",
      before: "<ul><li>React</li><li>TypeScript</li></ul>",
      after: "<ul><li>Professional skills: React, TypeScript</li><li>Language: English</li></ul>",
    }],
  };
  const richListMarkup = renderSummary([richListEdit]);
  assert.doesNotMatch(
    richListMarkup,
    /&lt;\/?(?:ul|li)&gt;/,
    "Change summaries must not expose rich-text storage tags to users.",
  );
  assert.match(richListMarkup, /• React/);
  assert.match(richListMarkup, /• Professional skills: React, TypeScript/);

  const locallyMergedMarkup = renderSummary(
    [multiFieldEdit],
    [{ ...multiFieldEdit.diffs[0], label: "Generic local edit" }],
  );
  assert.match(
    locallyMergedMarkup,
    /1 changes ready/,
    "The summary count must reflect only fields that remain in the local three-way merge.",
  );
  assert.match(locallyMergedMarkup, /aria-label="Project Description"/);
  assert.doesNotMatch(locallyMergedMarkup, />Project Description</);
  assert.doesNotMatch(
    locallyMergedMarkup,
    /aria-label="Generic local edit"/,
    "Local merge values must retain the canonical field label from the server observation.",
  );
  assert.doesNotMatch(
    locallyMergedMarkup,
    /aria-label="Project Highlights"/,
    "A field already satisfied by a concurrent local edit must not remain in the draft summary.",
  );

  const sameTargetMarkup = renderSummary(sameTargetEdits);
  assert.equal((sameTargetMarkup.match(/aria-label="Summary"/g) ?? []).length, 1);
  assert.doesNotMatch(sameTargetMarkup, />Summary</);
  assert.match(sameTargetMarkup, /1 changes ready/);
  assert.match(sameTargetMarkup, />A</);
  assert.match(sameTargetMarkup, />C</);

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
  const revertedMarkup = renderSummary(revertedEdits);
  assert.match(revertedMarkup, /0 changes ready/);
  assert.doesNotMatch(revertedMarkup, />Summary</);
  assert.doesNotMatch(revertedMarkup, />A</);
  assert.doesNotMatch(revertedMarkup, />B</);
} finally {
  await server.close();
}

console.log("Agent draft diff value checks passed.");
