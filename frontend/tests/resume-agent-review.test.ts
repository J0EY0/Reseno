// @vitest-environment node

import type {
  AgentResumeEditSuggestion,
  AgentDraftReviewItem,
} from "@/types/api";
import type { ExperienceItem } from "@/types/resume";
import { assert, describe, expect, it } from "vitest";
import { applyAgentEditsToDraft } from "@/lib/resume-agent-edits";
import {
  createProvisionalAgentDraftReviewItems,
  createReviewItemIdByOperationId,
  getAdjacentAgentDraftReviewItemId,
  getAgentDraftReviewSuccessorId,
  getPendingAgentDraftReviewItems,
  previewAgentDraftReview,
  projectAgentDraftReview,
} from "@/lib/agent-draft-review";
import { createResume } from "./helpers/agent-edit-fixtures";

it("projects only the pending items selected for review", async () => {
  const baseResume = createResume();
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "review-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Use the requested role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Frontend Engineer",
      },
    },
    {
      id: "review-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Focus the introduction.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Frontend-focused summary",
      },
    },
  ];
  const reviewItems = createProvisionalAgentDraftReviewItems(edits);
  const allProjection = projectAgentDraftReview({
    baseResume,
    currentResume: baseResume,
    edits,
    reviewItems,
  });
  const singleProjection = projectAgentDraftReview({
    baseResume,
    currentResume: baseResume,
    edits,
    reviewItemIds: [reviewItems[0].id],
    reviewItems,
  });

  assert(
    allProjection.resume.basic.headline === "Frontend Engineer" &&
      allProjection.resume.basic.summary === "Frontend-focused summary" &&
      allProjection.diffs.length === 2,
    "All-mode review must render every pending review item.",
  );
  assert(
    singleProjection.resume.basic.headline === "Frontend Engineer" &&
      singleProjection.resume.basic.summary === "Original summary" &&
      singleProjection.diffs.length === 1,
    "Single-mode review must remove every other pending proposal from the rendered resume.",
  );
  assert(
    createReviewItemIdByOperationId(reviewItems)["review-summary"] ===
      reviewItems[1].id &&
      getAdjacentAgentDraftReviewItemId(reviewItems, null, 1) ===
        reviewItems[0].id &&
      getAdjacentAgentDraftReviewItemId(reviewItems, reviewItems[0].id, -1) ===
        reviewItems[1].id,
    "Review navigation and operation mapping must use stable review-item ids.",
  );

  const resolvedItems = structuredClone(reviewItems);
  resolvedItems[0].status = "applied";
  const remainingItems = getPendingAgentDraftReviewItems(resolvedItems);
  assert(
    remainingItems.length === 1 &&
      getAgentDraftReviewSuccessorId(
        reviewItems,
        remainingItems,
        reviewItems[0].id,
      ) === reviewItems[1].id,
    "Resolving one item must decrement the pending count and select its successor.",
  );
});

it("retains manual changes while advancing individual review items", async () => {
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.headline = "User-edited headline";
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "partial-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the introduction.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
    {
      id: "partial-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the target role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Agent-edited headline",
      },
    },
  ];
  const reviewItems = createProvisionalAgentDraftReviewItems(edits);
  const appliedSummary = projectAgentDraftReview({
    baseResume,
    currentResume,
    edits,
    reviewItemIds: [reviewItems[0].id],
    reviewItems,
  });
  const remainingReviewItems = structuredClone(reviewItems);
  remainingReviewItems[0].status = "applied";
  const headlineAfterSummaryApply = projectAgentDraftReview({
    baseResume,
    currentResume: appliedSummary.resume,
    edits,
    reviewItemIds: [remainingReviewItems[1].id],
    reviewItems: remainingReviewItems,
  });

  assert(
    appliedSummary.errors.length === 0 &&
      appliedSummary.resume.basic.summary === "Agent-edited summary" &&
      appliedSummary.resume.basic.headline === "User-edited headline",
    "Applying one review item must preserve a disjoint local edit in the formal candidate.",
  );
  assert(
    headlineAfterSummaryApply.errors.length === 1 &&
      headlineAfterSummaryApply.errors[0].reason === "conflict" &&
      headlineAfterSummaryApply.resume.basic.headline ===
        "User-edited headline",
    "A later review item must still compare with the immutable draft base and reject a competing local edit.",
  );

  const inputSnapshot = JSON.stringify({
    baseResume,
    currentResume,
    edits,
    reviewItems,
  });
  const input: Parameters<typeof projectAgentDraftReview>[0] = {
    baseResume,
    currentResume,
    edits,
    reviewItems,
  };
  const preview = previewAgentDraftReview(input);
  assert(
    preview.conflicts.length === 1 &&
      preview.conflicts[0].reviewItemId === reviewItems[1].id &&
      preview.conflicts[0].diffs[0]?.before === "Engineer" &&
      preview.conflicts[0].diffs[0]?.after === "Agent-edited headline" &&
      preview.resume.basic.headline === "User-edited headline" &&
      preview.resume.basic.summary === "Agent-edited summary" &&
      preview.diffs.length === 1 &&
      preview.diffs[0].operationId === edits[0].id,
    "A competing manual edit must retain its original proposal for review while independent previews stay visible.",
  );
  const strictProjection = projectAgentDraftReview(input);
  assert(
    strictProjection.errors[0]?.reason === "conflict" &&
      strictProjection.diffs.length === 0 &&
      JSON.stringify(strictProjection.resume) === JSON.stringify(currentResume),
    "A preview containing safe suggestions must not turn an atomic apply into a partial save.",
  );
  for (const selected of reviewItems) {
    const selectedPreview = previewAgentDraftReview({
      ...input,
      reviewItemIds: [selected.id],
    });
    assert(
      selectedPreview.reviewItemIds.join() === selected.id &&
        selectedPreview.conflicts.length ===
          (selected.id === reviewItems[1].id ? 1 : 0) &&
        selectedPreview.diffs.length ===
          (selected.id === reviewItems[0].id ? 1 : 0),
      "Single-item navigation must scope both conflict notices and safe previews to the selected item.",
    );
  }
  const groupedPreview = previewAgentDraftReview({
    ...input,
    reviewItems: [
      {
        id: "atomic-group",
        editIds: edits.map((edit) => edit.id),
        status: "pending",
      },
    ],
  });
  assert(
    groupedPreview.conflicts.length === 1 &&
      groupedPreview.conflicts[0].diffs.length === 2 &&
      groupedPreview.diffs.length === 0 &&
      JSON.stringify(groupedPreview.resume) === JSON.stringify(currentResume),
    "A conflicted review group must remain indivisible even when one operation is safe.",
  );
  const restoredPreview = previewAgentDraftReview({
    ...input,
    currentResume: baseResume,
  });
  assert(
    restoredPreview.conflicts.length === 0 &&
      restoredPreview.diffs.length === 2,
    "Restoring the original field must immediately make the stored suggestions reviewable again.",
  );
  const twoConflicts = previewAgentDraftReview({
    ...input,
    currentResume: {
      ...currentResume,
      basic: { ...currentResume.basic, summary: "Manual summary" },
    },
  });
  assert(
    twoConflicts.conflicts.length === 2 &&
      twoConflicts.errors.length === 2 &&
      twoConflicts.diffs.length === 0,
    "Every conflicting review item must remain available for inspection.",
  );
  assert(
    inputSnapshot ===
      JSON.stringify({ baseResume, currentResume, edits, reviewItems }),
    "Reviewing conflicts must not mutate the draft base, current document, edits, or decisions.",
  );
});

it("retains reviewable deleted targets and rejects malformed drafts", async () => {
  const baseResume = createResume();
  const currentResume = { ...structuredClone(baseResume), sections: [] };
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "rename-removed-section",
      title: "Rename education",
      target: "sections.education.title",
      reason: "Rename",
      operation: {
        type: "update_section",
        sectionId: "education",
        patch: { title: "Learning" },
      },
    },
    {
      id: "independent-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Update",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent summary",
      },
    },
  ];
  const input: Parameters<typeof projectAgentDraftReview>[0] = {
    baseResume,
    currentResume,
    edits,
    reviewItems: createProvisionalAgentDraftReviewItems(edits),
  };
  const preview = previewAgentDraftReview(input);
  assert(
    preview.conflicts.length === 1 &&
      preview.conflicts[0].diffs.length === 1 &&
      preview.resume.sections.length === 0 &&
      preview.resume.basic.summary === "Agent summary",
    "Deleting a draft target must preserve the deletion and its reviewable proposal without hiding independent suggestions.",
  );
  const invalidEdits = [
    ...edits,
    {
      id: "invalid",
      title: "Invalid",
      target: "basic.name",
      reason: "Invalid",
      operation: { type: "unknown" },
    },
  ] as unknown as AgentResumeEditSuggestion[];
  const invalid = previewAgentDraftReview({
    ...input,
    edits: invalidEdits,
    reviewItems: createProvisionalAgentDraftReviewItems(invalidEdits),
  });
  assert(
    invalid.errors[0]?.reason === "invalid_operation" &&
      invalid.conflicts.length === 0 &&
      invalid.diffs.length === 0 &&
      JSON.stringify(invalid.resume) === JSON.stringify(currentResume),
    "Malformed drafts must still be rejected atomically rather than shown as editable conflicts.",
  );
});

function createWholeDraftInput() {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "work",
    kind: "experience",
    title: "Work",
    items: [
      {
        id: "job",
        company: "Company",
        position: "Engineer",
        period: "2024",
        location: "",
        description: "Original description",
        highlights: ["Original achievement"],
      },
    ],
  });
  const currentResume = structuredClone(baseResume);
  Object.assign(currentResume.basic, {
    name: "Manual name",
    headline: "Manual headline after applying",
    summary: "Manual summary",
  });
  currentResume.sections[1].title = "Manual title";
  Object.assign(currentResume.sections[1].items[0], {
    company: "Manual company",
    location: "Manual location",
    highlights: ["Manual achievement"],
  });
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "applied-headline",
      title: "Headline",
      target: "basic.headline",
      reason: "Requested change",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
    {
      id: "discarded-summary",
      title: "Summary",
      target: "basic.summary",
      reason: "Requested change",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Discarded summary",
      },
    },
    {
      id: "pending-title",
      title: "Section title",
      target: "sections.work.title",
      reason: "Requested change",
      operation: {
        type: "update_section",
        sectionId: "work",
        patch: { title: "Career" },
      },
    },
    {
      id: "pending-work",
      title: "Work",
      target: "sections.work.items.job",
      reason: "Requested change",
      operation: {
        type: "update_item",
        sectionId: "work",
        itemId: "job",
        patch: {
          company: "Agent company",
          position: "Senior Engineer",
          location: "",
          highlights: ["Agent achievement"],
        },
      },
    },
  ];
  const reviewItems: AgentDraftReviewItem[] = edits.map((edit, index) => ({
    id: edit.id,
    editIds: [edit.id],
    status: index === 0 ? "applied" : index === 1 ? "discarded" : "pending",
  }));
  return {
    baseResume,
    currentResume,
    edits,
    reviewItems,
    reviewItemIds: ["pending-title", "pending-work"],
  };
}

describe.each(["use-original", "keep-manual"] as const)(
  "%s whole-draft resolution",
  (conflictResolution) => {
    it("resolves every pending group while preserving inputs", () => {
      const input = createWholeDraftInput();
      const snapshot = structuredClone(input);
      const result = projectAgentDraftReview({ ...input, conflictResolution });
      expect(result.errors).toEqual([]);
      expect(result.reviewItemIds).toEqual(input.reviewItemIds);
      expect(input).toEqual(snapshot);
      const item = result.resume.sections[1].items[0] as ExperienceItem;
      if (conflictResolution === "use-original") {
        expect(result.resume.basic).toMatchObject({
          name: "Original name",
          headline: "Staff Engineer",
          summary: "Original summary",
        });
        expect(result.resume.sections[1].title).toBe("Career");
        expect(item).toMatchObject({
          company: "Agent company",
          position: "Senior Engineer",
          location: "",
          highlights: ["Agent achievement"],
        });
      } else {
        expect(result.resume.basic).toEqual(input.currentResume.basic);
        expect(result.resume.sections[1].title).toBe("Manual title");
        expect(item).toMatchObject({
          company: "Manual company",
          position: "Senior Engineer",
          location: "Manual location",
          highlights: ["Manual achievement"],
        });
        expect(result.diffs).toHaveLength(1);
        expect(result.diffs[0].path).toBe("sections.work.items.job.position");
      }
    });

    it.each([
      { scope: "missing", reviewItemIds: undefined },
      { scope: "empty", reviewItemIds: [] },
      { scope: "partial", reviewItemIds: ["pending-work"] },
      {
        scope: "includes applied",
        reviewItemIds: ["pending-title", "pending-work", "applied-headline"],
      },
      {
        scope: "includes discarded",
        reviewItemIds: ["pending-title", "pending-work", "discarded-summary"],
      },
      { scope: "duplicate", reviewItemIds: ["pending-title", "pending-title"] },
      {
        scope: "unknown",
        reviewItemIds: ["pending-title", "pending-work", "unknown"],
      },
    ])("rejects $scope review scope", ({ reviewItemIds }) => {
      const input = createWholeDraftInput();
      expect(() =>
        projectAgentDraftReview({
          ...input,
          conflictResolution,
          reviewItemIds,
        }),
      ).toThrow();
    });

    it("excludes superseded suggestions from the complete result", () => {
      const input = createWholeDraftInput();
      const expected = projectAgentDraftReview({
        ...input,
        conflictResolution,
      });
      const result = projectAgentDraftReview({
        ...input,
        conflictResolution,
        reviewItems: input.reviewItems.map((item) =>
          item.status === "discarded"
            ? { ...item, status: "superseded" }
            : item,
        ),
      });
      expect(result.errors).toEqual([]);
      expect(result.resume).toEqual(expected.resume);
    });

    it("replays durable operation order despite reversed selection order", () => {
      const input = createWholeDraftInput();
      const expected = projectAgentDraftReview({
        ...input,
        conflictResolution,
      });
      const result = projectAgentDraftReview({
        ...input,
        conflictResolution,
        reviewItemIds: [...input.reviewItemIds].reverse(),
      });
      expect(result.resume).toEqual(expected.resume);
    });

    it("rejects malformed operations atomically", () => {
      const input = createWholeDraftInput();
      const result = projectAgentDraftReview({
        ...input,
        conflictResolution,
        edits: [
          ...input.edits,
          {
            id: "invalid",
            title: "Invalid",
            target: "basic.name",
            reason: "Invalid",
            operation: { type: "unknown" },
          },
        ] as unknown as AgentResumeEditSuggestion[],
        reviewItemIds: [...input.reviewItemIds, "invalid"],
        reviewItems: [
          ...input.reviewItems,
          { id: "invalid", editIds: ["invalid"], status: "pending" },
        ],
      });
      expect(result.errors[0]?.reason).toBe("invalid_operation");
      expect(result.diffs).toEqual([]);
      expect(result.resume).toEqual(input.currentResume);
    });

    it.each(["deleted", "kind"])("handles a manually %s target", (change) => {
      const input = createWholeDraftInput();
      const original = projectAgentDraftReview({
        ...input,
        conflictResolution: "use-original",
      });
      const changed = structuredClone(input.currentResume);
      if (change === "deleted") changed.sections[1].items = [];
      else
        changed.sections[1] = {
          id: "work",
          kind: "project",
          title: "Manual project",
          items: [],
        };
      const result = projectAgentDraftReview({
        ...input,
        currentResume: changed,
        conflictResolution,
      });
      expect(result.errors).toEqual([]);
      expect(result.resume).toEqual(
        conflictResolution === "use-original" ? original.resume : changed,
      );
    });
  },
);

it("keeps ordinary per-item review strict without mutating inputs", () => {
  const input = createWholeDraftInput();
  const snapshot = structuredClone(input);
  const result = projectAgentDraftReview({
    ...input,
    reviewItemIds: ["pending-work"],
  });
  expect(result.errors[0]?.reason).toBe("conflict");
  expect(input).toEqual(snapshot);
});

it("keeps dependent structural groups together during conflict resolution", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "projects",
    kind: "project",
    title: "Projects",
    items: [],
  });
  const currentResume = structuredClone(baseResume);
  currentResume.sections[0].title = "Manual education";
  currentResume.sections.push({
    id: "manual",
    kind: "education",
    title: "Manual section",
    items: [],
  });
  const prefix: AgentResumeEditSuggestion = {
    id: "prefix",
    title: "Headline",
    target: "basic.headline",
    reason: "Requested change",
    operation: {
      type: "replace_field",
      path: "basic.headline",
      value: "Agent headline",
    },
  };
  const independent: AgentResumeEditSuggestion = {
    id: "independent",
    title: "Summary",
    target: "basic.summary",
    reason: "Requested change",
    operation: {
      type: "replace_field",
      path: "basic.summary",
      value: "Agent summary",
    },
  };
  for (const operation of [
    { type: "delete_section", sectionId: "education" },
    {
      type: "insert_section",
      section: { id: "new", kind: "project", title: "New", items: [] },
    },
    { type: "reorder_sections", sectionIds: ["projects", "education"] },
  ] satisfies AgentResumeEditSuggestion["operation"][]) {
    const structural: AgentResumeEditSuggestion = {
      id: "structure",
      title: "Structure",
      target: "sections",
      reason: "Requested change",
      operation,
    };
    const edits: AgentResumeEditSuggestion[] = [
      prefix,
      structural,
      independent,
    ];
    const input: Parameters<typeof projectAgentDraftReview>[0] = {
      baseResume,
      currentResume,
      edits,
      reviewItems: [
        {
          id: "dependent",
          editIds: ["prefix", "structure"],
          status: "pending",
        },
        { id: "independent", editIds: ["independent"], status: "pending" },
      ],
      reviewItemIds: ["dependent", "independent"],
    };
    const kept = projectAgentDraftReview({
      ...input,
      conflictResolution: "keep-manual",
    });
    const expected = {
      ...currentResume,
      basic: { ...currentResume.basic, summary: "Agent summary" },
    };
    assert(
      kept.errors.length === 0 &&
        kept.diffs.length === 1 &&
        JSON.stringify(kept.resume) === JSON.stringify(expected),
      "A manual structural conflict must preserve its entire dependency group while independent Agent groups still merge.",
    );
    const original = projectAgentDraftReview({
      ...input,
      conflictResolution: "use-original",
    });
    const proposed = applyAgentEditsToDraft(baseResume, edits);
    assert(
      original.errors.length === 0 &&
        JSON.stringify(original.resume) === JSON.stringify(proposed.resume),
      "The original choice must rebuild the Agent structure without later manually added sections.",
    );
  }
});

it("keeps manual values that match an intermediate Agent write", async () => {
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.headline = "Staff Engineer";
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "first",
      title: "First",
      target: "basic.headline",
      reason: "Requested change",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
    {
      id: "second",
      title: "Second",
      target: "basic.headline",
      reason: "Requested change",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Principal Engineer",
      },
    },
    {
      id: "safe",
      title: "Safe",
      target: "basic.summary",
      reason: "Requested change",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent summary",
      },
    },
  ];
  const input: Parameters<typeof projectAgentDraftReview>[0] = {
    baseResume,
    currentResume,
    edits,
    reviewItemIds: ["dependent", "safe"],
    reviewItems: [
      { id: "dependent", editIds: ["first", "second"], status: "pending" },
      { id: "safe", editIds: ["safe"], status: "pending" },
    ],
  };
  const kept = projectAgentDraftReview({
    ...input,
    conflictResolution: "keep-manual",
  });
  assert(
    kept.errors.length === 0 &&
      kept.resume.basic.headline === "Staff Engineer" &&
      kept.resume.basic.summary === "Agent summary",
    "A manual value that matches an intermediate Agent write must retain priority over later writes in that group.",
  );
  const original = projectAgentDraftReview({
    ...input,
    conflictResolution: "use-original",
  });
  assert(
    original.errors.length === 0 &&
      original.resume.basic.headline === "Principal Engineer",
    "The original result must replay every sequential Agent write.",
  );
});

it("preserves a manually edited item against a later dependent deletion", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "work",
    kind: "experience",
    title: "Work",
    items: [
      {
        id: "job",
        company: "Company",
        position: "Engineer",
        period: "",
        location: "",
        description: "",
        highlights: [],
      },
    ],
  });
  const currentResume = structuredClone(baseResume);
  (currentResume.sections[1].items[0] as ExperienceItem).company =
    "Manual company";
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "first",
      title: "First",
      target: "sections.work.items.job",
      reason: "Requested change",
      operation: {
        type: "update_item",
        sectionId: "work",
        itemId: "job",
        patch: { company: "Manual company" },
      },
    },
    {
      id: "second",
      title: "Second",
      target: "sections.work.items.job",
      reason: "Requested change",
      operation: { type: "delete_item", sectionId: "work", itemId: "job" },
    },
  ];
  const input: Parameters<typeof projectAgentDraftReview>[0] = {
    baseResume,
    currentResume,
    edits,
    reviewItemIds: ["dependent"],
    reviewItems: [
      { id: "dependent", editIds: ["first", "second"], status: "pending" },
    ],
  };
  const kept = projectAgentDraftReview({
    ...input,
    conflictResolution: "keep-manual",
  });
  assert(
    kept.errors.length === 0 &&
      JSON.stringify(kept.resume) === JSON.stringify(currentResume),
    "Matching an intermediate Agent field value must not allow a later deletion to erase a manually changed item.",
  );
});
