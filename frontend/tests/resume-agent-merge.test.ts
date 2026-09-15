// @vitest-environment node

import type { AgentResumeEditSuggestion } from "@/types/api";
import type { ExperienceItem } from "@/types/resume";
import { assert, it } from "vitest";
import {
  applyAgentEditsWithMerge,
  createAgentDraftBaseSnapshot,
} from "@/lib/resume-agent-edits";
import { createResume } from "./helpers/agent-edit-fixtures";

it("merges disjoint manual and Agent fields", async () => {
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.name = "User-edited name";
  const result = applyAgentEditsWithMerge(baseResume, currentResume, [
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
  ]);

  assert(result.errors.length === 0, "Disjoint field edits must merge.");
  assert(
    result.resume.basic.name === "User-edited name" &&
      result.resume.basic.summary === "Agent-edited summary",
    "A merge must preserve the user's concurrent field edit.",
  );
});

it("keeps both inputs immutable and handles pending convergent and conflicting fields", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "work",
    kind: "experience",
    title: "Work",
    items: [
      {
        id: "job",
        company: "Original company",
        position: "Engineer",
        period: "2024",
        location: "",
        description: "Original description",
        highlights: ["Original achievement"],
      },
    ],
  });
  const baseBefore = JSON.stringify(baseResume);
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Use the requested headline.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
    {
      id: "update-work",
      title: "Update work",
      target: "sections.work.items.job",
      reason: "Use the requested role.",
      operation: {
        type: "update_item",
        sectionId: "work",
        itemId: "job",
        patch: {
          company: "Original company",
          position: "Senior Engineer",
          highlights: ["Original achievement"],
        },
      },
    },
  ];
  for (const position of ["Engineer", "Senior Engineer", "Manual role"]) {
    const currentResume = structuredClone(baseResume);
    const currentItem = currentResume.sections[1].items[0];
    Object.assign(currentItem, {
      company: "Manual company",
      location: "Manual location",
      position,
      highlights: ["Manual achievement"],
    });
    const currentBefore = JSON.stringify(currentResume);
    const result = applyAgentEditsWithMerge(baseResume, currentResume, edits);
    assert(
      JSON.stringify(baseResume) === baseBefore &&
        JSON.stringify(currentResume) === currentBefore,
      "Three-way merges must leave both input documents immutable.",
    );
    if (position === "Manual role") {
      assert(
        result.errors.length === 1 &&
          result.errors[0].reason === "conflict" &&
          result.errors[0].target === "sections.work.items.job.position" &&
          result.appliedCount === 0 &&
          result.diffs.length === 0 &&
          JSON.stringify(result.resume) === currentBefore,
        "A true field conflict must roll back all earlier edits in the batch.",
      );
      continue;
    }
    const mergedItem = result.resume.sections[1].items[0] as ExperienceItem;
    assert(
      result.errors.length === 0 &&
        result.resume.basic.headline === "Staff Engineer" &&
        mergedItem.company === "Manual company" &&
        mergedItem.location === "Manual location" &&
        JSON.stringify(mergedItem.highlights) ===
          JSON.stringify(["Manual achievement"]) &&
        mergedItem.position === "Senior Engineer",
      "Unchanged fields repeated in a patch must preserve manual scalar and array values.",
    );
    assert(
      result.appliedCount === (position === "Engineer" ? 2 : 1) &&
        JSON.stringify(result.diffs.map((diff) => diff.path)) ===
          JSON.stringify(
            position === "Engineer"
              ? ["basic.headline", "sections.work.items.job.position"]
              : ["basic.headline"],
          ),
      "Only pending Agent changes should produce diffs, excluding convergent values.",
    );
  }
});

it("rejects competing edits to the same field", async () => {
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.summary = "User-edited summary";
  const result = applyAgentEditsWithMerge(baseResume, currentResume, [
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
  ]);

  assert(
    result.errors.length === 1 && result.errors[0].reason === "conflict",
    "Competing edits to the same field must reject the candidate.",
  );
  assert(
    result.resume.basic.summary === "User-edited summary",
    "A conflict must leave the current resume untouched.",
  );
});

it("merges unique structural inserts with manual changes", async () => {
  const baseResume = createResume();
  const currentResume = structuredClone(baseResume);
  currentResume.basic.name = "User-edited name";
  const result = applyAgentEditsWithMerge(baseResume, currentResume, [
    {
      id: "insert-projects",
      title: "Add projects",
      target: "sections.projects",
      reason: "Add project evidence.",
      operation: {
        type: "insert_section",
        index: 1,
        section: {
          id: "projects",
          kind: "project",
          title: "Projects",
          items: [],
        },
      },
    },
  ]);

  assert(result.errors.length === 0, "A unique structural insert must merge.");
  assert(
    result.resume.basic.name === "User-edited name" &&
      result.resume.sections[1]?.id === "projects",
    "A structural insert must retain unrelated user field edits.",
  );
});

it("rejects concurrent structural changes", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "projects",
    kind: "project",
    title: "Projects",
    items: [],
  });
  const currentResume = structuredClone(baseResume);
  currentResume.sections.push({
    id: "skills",
    kind: "simple_list",
    title: "Skills",
    items: [{ id: "skill-1", content: "<ul><li>React</li></ul>" }],
  });
  const result = applyAgentEditsWithMerge(baseResume, currentResume, [
    {
      id: "reorder-sections",
      title: "Prioritize projects",
      target: "sections",
      reason: "Lead with project evidence.",
      operation: {
        type: "reorder_sections",
        sectionIds: ["projects", "education"],
      },
    },
  ]);

  assert(
    result.errors.length === 1 && result.errors[0].reason === "conflict",
    "Concurrent structural changes must reject the candidate.",
  );
  assert(
    result.resume.sections.map((section) => section.id).join("|") ===
      "education|projects|skills",
    "A structural conflict must not reorder the current resume.",
  );
});

it("rebases a stored draft onto later manual edits", async () => {
  const baseResume = createResume();
  const draftBase = createAgentDraftBaseSnapshot(baseResume);
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
  ];
  const generatedDraft = applyAgentEditsWithMerge(draftBase, baseResume, edits);
  const latestResume = structuredClone(baseResume);
  latestResume.basic.name = "User edit after draft generation";
  const appliedDraft = applyAgentEditsWithMerge(draftBase, latestResume, edits);

  assert(
    generatedDraft.resume.basic.summary === "Agent-edited summary",
    "Draft generation must still preview the Agent batch.",
  );
  assert(
    appliedDraft.errors.length === 0 &&
      appliedDraft.resume.basic.name === "User edit after draft generation" &&
      appliedDraft.resume.basic.summary === "Agent-edited summary",
    "Applying a stored draft must rebase onto manual edits made after draft generation.",
  );
});

it("refines a pending draft from the immutable transaction base", async () => {
  const originalResume = createResume();
  const transactionBase = createAgentDraftBaseSnapshot(originalResume);
  const firstDraftEdits: AgentResumeEditSuggestion[] = [
    {
      id: "initial-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Create the first pending draft.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
  ];
  const firstDraft = applyAgentEditsWithMerge(
    transactionBase,
    originalResume,
    firstDraftEdits,
  );
  const followUpEdits: AgentResumeEditSuggestion[] = [
    {
      id: "refined-headline",
      title: "Refine headline",
      target: "basic.headline",
      reason: "Continue from the pending Staff Engineer candidate.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Principal Engineer",
      },
    },
    {
      id: "follow-up-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Apply a disjoint follow-up edit.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Focused summary",
      },
    },
  ];
  const refinedDraft = applyAgentEditsWithMerge(
    transactionBase,
    originalResume,
    [...firstDraftEdits, ...followUpEdits],
  );

  assert(
    firstDraft.errors.length === 0 &&
      firstDraft.resume.basic.headline === "Staff Engineer",
    "The first pending draft must be a valid candidate built from the immutable base.",
  );
  assert(
    refinedDraft.errors.length === 0 &&
      refinedDraft.resume.basic.headline === "Principal Engineer" &&
      refinedDraft.resume.basic.summary === "Focused summary",
    "A follow-up must replace the same field without conflict and preserve every prior edit.",
  );
});

it("rejects competing edits made after draft generation", async () => {
  const baseResume = createResume();
  const draftBase = createAgentDraftBaseSnapshot(baseResume);
  const edits: AgentResumeEditSuggestion[] = [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the candidate's role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Agent-edited headline",
      },
    },
    {
      id: "update-summary",
      title: "Update summary",
      target: "basic.summary",
      reason: "Improve the opening statement.",
      operation: {
        type: "replace_field",
        path: "basic.summary",
        value: "Agent-edited summary",
      },
    },
  ];
  const latestResume = structuredClone(baseResume);
  latestResume.basic.summary = "User edit after draft generation";
  const appliedDraft = applyAgentEditsWithMerge(draftBase, latestResume, edits);

  assert(
    appliedDraft.errors.length === 1 &&
      appliedDraft.errors[0].reason === "conflict",
    "A competing manual edit made after draft generation must reject the draft.",
  );
  assert(
    appliedDraft.appliedCount === 0 &&
      appliedDraft.resume.basic.headline === "Engineer" &&
      appliedDraft.resume.basic.summary === "User edit after draft generation",
    "A late conflict must leave the complete current resume untouched.",
  );
});
