// @vitest-environment node

import type { AgentResumeEditSuggestion } from "@/types/api";
import type { ExperienceItem, SimpleListItem } from "@/types/resume";
import { assert, it } from "vitest";
import * as agentEditModule from "@/lib/resume-agent-edits";
import {
  applyAgentEditsToDraft,
  applyAgentEditsWithMerge,
} from "@/lib/resume-agent-edits";
import { createResume } from "./helpers/agent-edit-fixtures";

it("exposes exactly the three edit transaction APIs", async () => {
  assert(
    JSON.stringify(Object.keys(agentEditModule).sort()) ===
      JSON.stringify([
        "applyAgentEditsToDraft",
        "applyAgentEditsWithMerge",
        "createAgentDraftBaseSnapshot",
      ]),
    "The Resume Agent edit runtime entry must expose exactly the three product APIs.",
  );
});

it("rejects edits without executable operations", async () => {
  const baseResume = createResume();
  const legacyEdit = {
    id: "missing-operation",
    title: "Update summary",
    target: "basic.summary",
    reason: "Use the supplied description.",
    replacement: "Summary without an executable operation",
  };
  for (const result of [
    applyAgentEditsToDraft(baseResume, [
      legacyEdit as unknown as AgentResumeEditSuggestion,
    ]),
    applyAgentEditsWithMerge(baseResume, baseResume, [
      legacyEdit as unknown as AgentResumeEditSuggestion,
    ]),
  ]) {
    assert(
      result.appliedCount === 0 &&
        result.diffs.length === 0 &&
        result.errors[0]?.reason === "missing_operation" &&
        JSON.stringify(result.resume) === JSON.stringify(baseResume),
      "An edit without an explicit operation must leave the resume unchanged.",
    );
  }
});

it("reports the minimal deterministic moved item set", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "experience",
    kind: "experience",
    title: "Experience",
    items: ["first", "second", "third", "fourth"].map((id) => ({
      id,
      company: id,
      position: "",
      location: "",
      period: "",
      description: "",
      highlights: [],
    })),
  });
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "reorder-items-precisely",
      title: "Reorder experience",
      target: "sections.experience.items",
      reason: "Verify each changed object.",
      operation: {
        type: "reorder_items",
        sectionId: "experience",
        itemIds: ["second", "fourth", "first", "third"],
      },
    },
  ]);

  assert(
    JSON.stringify(
      result.diffs.map((diff) => ({
        path: diff.path,
        itemId: diff.itemId,
        before: diff.before,
        after: diff.after,
      })),
    ) ===
      JSON.stringify([
        {
          path: "sections.experience.items.first",
          itemId: "first",
          before: 0,
          after: 2,
        },
        {
          path: "sections.experience.items.third",
          itemId: "third",
          before: 2,
          after: 3,
        },
      ]),
    "An item reorder must mark the deterministic minimal moved set from the longest common subsequence.",
  );
});

it("retains stable neighbors in structural deletion diffs", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "experience",
    kind: "experience",
    title: "Experience",
    items: [
      {
        id: "first",
        company: "First",
        position: "",
        location: "",
        period: "",
        description: "",
        highlights: [],
      },
      {
        id: "second",
        company: "Second",
        position: "",
        location: "",
        period: "",
        description: "",
        highlights: [],
      },
    ],
  });
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "delete-second-item",
      title: "Delete second item",
      target: "sections.experience.items.second",
      reason: "Verify the exact review boundary.",
      operation: {
        type: "delete_item",
        sectionId: "experience",
        itemId: "second",
      },
    },
    {
      id: "delete-education-section",
      title: "Delete education",
      target: "sections.education",
      reason: "Verify the exact review boundary.",
      operation: {
        type: "delete_section",
        sectionId: "education",
      },
    },
  ]);

  assert(
    result.diffs[0]?.beforePreviousId === "first" &&
      result.diffs[0]?.beforeNextId === undefined &&
      result.diffs[1]?.beforePreviousId === undefined &&
      result.diffs[1]?.beforeNextId === "experience",
    "Structural deletion diffs must retain stable pre-deletion neighbors.",
  );
});

it("reports only the section moved to the end", async () => {
  const baseResume = createResume();
  baseResume.sections.push(
    {
      id: "experience",
      kind: "experience",
      title: "Experience",
      items: [],
    },
    {
      id: "projects",
      kind: "project",
      title: "Projects",
      items: [],
    },
  );
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "reorder-sections-precisely",
      title: "Reorder sections",
      target: "sections",
      reason: "Verify each changed object.",
      operation: {
        type: "reorder_sections",
        sectionIds: ["experience", "projects", "education"],
      },
    },
  ]);

  assert(
    JSON.stringify(
      result.diffs.map((diff) => ({
        path: diff.path,
        sectionId: diff.sectionId,
        before: diff.before,
        after: diff.after,
      })),
    ) ===
      JSON.stringify([
        {
          path: "sections.education",
          sectionId: "education",
          before: 0,
          after: 2,
        },
      ]),
    "Moving the first section to the end must mark only that section as moved.",
  );
});

it("rolls back every edit when any operation fails", async () => {
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the candidate's role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
    {
      id: "delete-missing-section",
      title: "Delete missing section",
      target: "sections.missing",
      reason: "Exercise transaction rollback.",
      operation: {
        type: "delete_section",
        sectionId: "missing",
      },
    },
  ]);

  assert(
    result.appliedCount === 0,
    "A batch containing any failed edit must report zero applied edits.",
  );
  assert(
    result.diffs.length === 0,
    "A rejected batch must not expose partial diffs.",
  );
  assert(
    JSON.stringify(result.resume) === JSON.stringify(baseResume),
    "A rejected batch must return the original resume state.",
  );
  assert(
    result.errors.length === 1 &&
      result.errors[0].editId === "delete-missing-section" &&
      result.errors[0].reason === "target_not_found" &&
      result.errors[0].target === "sections.missing",
    "A rejected batch must return a structured, actionable error.",
  );
});

it("rejects fields outside the simple list content contract", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "skills",
    kind: "simple_list",
    title: "Skills",
    items: [
      {
        id: "skill-1",
        content: "React, TypeScript",
      },
    ],
  });
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-invalid-skills",
      title: "Add skill highlights",
      target: "sections.skills.items.skill-1",
      reason: "Exercise list-item update validation.",
      operation: {
        type: "update_item",
        sectionId: "skills",
        itemId: "skill-1",
        patch: { highlights: ["React"] },
      },
    },
  ]);

  assert(
    result.appliedCount === 0 &&
      result.errors.length === 1 &&
      result.errors[0].reason === "invalid_operation" &&
      (result.resume.sections[1].items[0] as SimpleListItem).content ===
        "React, TypeScript",
    "Simple-list updates must reject fields outside the content contract.",
  );
});

it.each([
  {
    type: "insert_item",
    sectionId: "skills",
    item: { id: "skill-2", content: "TypeScript" },
  },
  {
    type: "delete_item",
    sectionId: "skills",
    itemId: "skill-1",
  },
  {
    type: "reorder_items",
    sectionId: "skills",
    itemIds: ["skill-1"],
  },
] satisfies AgentResumeEditSuggestion["operation"][])(
  "rejects invalid operations for simple list items (%j)",
  async (operation) => {
    const baseResume = createResume();
    baseResume.sections.push({
      id: "skills",
      kind: "simple_list",
      title: "Skills",
      items: [{ id: "skill-1", content: "<ul><li>React</li></ul>" }],
    });
    const result = applyAgentEditsToDraft(baseResume, [
      {
        id: `reject-${operation.type}`,
        title: "Keep the single rich-text item",
        target: "sections.skills.items",
        reason: "Exercise the simple-list cardinality contract.",
        operation,
      },
    ]);

    assert(
      result.appliedCount === 0 &&
        result.errors.length === 1 &&
        result.errors[0].reason === "invalid_operation" &&
        JSON.stringify(result.resume) === JSON.stringify(baseResume),
      `Simple-list sections must reject ${operation.type}.`,
    );
  },
);

it("rejects invalid fields in inserted simple list sections", async () => {
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "insert-invalid-skills",
      title: "Add skills",
      target: "sections.skills",
      reason: "Exercise the canonical list-item contract.",
      operation: {
        type: "insert_section",
        section: {
          id: "skills",
          kind: "simple_list",
          title: "Skills",
          items: [
            {
              id: "skill-1",
              content: "Frontend",
              highlights: ["React"],
            },
          ],
        },
      } as unknown as AgentResumeEditSuggestion["operation"],
    },
  ]);

  assert(
    result.appliedCount === 0 &&
      result.errors.length === 1 &&
      result.errors[0].reason === "invalid_operation",
    "Simple-list sections must reject fields outside id and content.",
  );
});

it("applies semantic item fields with exact field diffs", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "experience",
    kind: "experience",
    title: "Experience",
    items: [
      {
        id: "experience-1",
        company: "Example Inc.",
        position: "Engineer",
        location: "Remote",
        period: "2024 - Present",
        description: "",
        highlights: [],
      },
    ],
  });
  baseResume.sections.push({
    id: "skills",
    kind: "simple_list",
    title: "Skills",
    items: [{ id: "skill-1", content: "React" }],
  });

  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-position",
      title: "Clarify the experience",
      target: "sections.experience.items.experience-1",
      reason: "Use the semantic experience fields.",
      operation: {
        type: "update_item",
        sectionId: "experience",
        itemId: "experience-1",
        patch: {
          position: "Senior Engineer",
          description: "Built the editor platform.",
          highlights: ["Reduced state complexity."],
        },
      },
    },
    {
      id: "update-skills",
      title: "Add a skill",
      target: "sections.skills.items.skill-1.content",
      reason: "A simple-list item remains a directly editable string.",
      operation: {
        type: "update_item",
        sectionId: "skills",
        itemId: "skill-1",
        patch: { content: "React · TypeScript" },
      },
    },
  ]);

  assert(
    result.errors.length === 0 && result.appliedCount === 2,
    "Valid semantic item fields must be applied atomically.",
  );
  assert(
    (result.resume.sections[1].items[0] as ExperienceItem).position ===
      "Senior Engineer" &&
      (result.resume.sections[1].items[0] as ExperienceItem).company ===
        "Example Inc." &&
      (result.resume.sections[2].items[0] as SimpleListItem).content ===
        "React · TypeScript",
    "Agent item edits must preserve unrelated fields and support simple-list strings.",
  );
  assert(
    result.diffs.length === 4,
    "One multi-field edit must expose one precise diff per changed field without changing applied edit count.",
  );
  assert(
    JSON.stringify(result.diffs.map((diff) => diff.path)) ===
      JSON.stringify([
        "sections.experience.items.experience-1.position",
        "sections.experience.items.experience-1.description",
        "sections.experience.items.experience-1.highlights",
        "sections.skills.items.skill-1.content",
      ]),
    "Item diffs must use canonical field paths instead of a whole-item target.",
  );
  assert(
    JSON.stringify(result.diffs[0]) ===
      JSON.stringify({
        id: "diff-update-position-position",
        operationId: "update-position",
        path: "sections.experience.items.experience-1.position",
        kind: "modified",
        label: "Clarify the experience",
        sectionId: "experience",
        itemId: "experience-1",
        before: "Engineer",
        after: "Senior Engineer",
      }),
    "A field diff must carry only that field's before and after values.",
  );
});

it("applies valid batches without mutating the source", async () => {
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the candidate's role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
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
        value: "Updated summary",
      },
    },
  ]);

  assert(result.errors.length === 0, "A valid batch must not return errors.");
  assert(result.appliedCount === 2, "A valid batch must commit every edit.");
  assert(result.diffs.length === 2, "A valid batch must expose every diff.");
  assert(
    result.resume.basic.headline === "Staff Engineer" &&
      result.resume.basic.summary === "Updated summary",
    "A valid batch must return the fully updated resume.",
  );
  assert(
    baseResume.basic.headline === "Engineer" &&
      baseResume.basic.summary === "Original summary",
    "Applying a batch must never mutate the source resume.",
  );
});

it("rejects hidden basic fields", async () => {
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "reject-location",
      title: "Reject hidden location",
      target: "basic.location",
      reason: "Location is outside the Agent write contract.",
      operation: {
        type: "replace_field",
        path: "basic.location",
        value: "Remote",
      } as unknown as AgentResumeEditSuggestion["operation"],
    },
  ]);

  assert(
    result.errors.length === 1 && result.appliedCount === 0,
    "Agent drafts must reject hidden basic fields on the frontend boundary.",
  );
  assert(
    result.resume.basic.location === "",
    "A rejected location edit must not change the resume.",
  );
});

it("rejects unknown operations and rolls back the batch", async () => {
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "update-headline",
      title: "Update headline",
      target: "basic.headline",
      reason: "Clarify the candidate's role.",
      operation: {
        type: "replace_field",
        path: "basic.headline",
        value: "Staff Engineer",
      },
    },
    {
      id: "unknown-operation",
      title: "Run unsupported operation",
      target: "sections.education",
      reason: "Exercise runtime payload validation.",
      operation: {
        type: "operation_from_a_newer_server",
      } as unknown as AgentResumeEditSuggestion["operation"],
    },
  ]);

  assert(
    result.appliedCount === 0 && result.resume.basic.headline === "Engineer",
    "An unknown operation must reject and roll back the entire batch.",
  );
  assert(
    result.errors.length === 1 &&
      result.errors[0].editId === "unknown-operation" &&
      result.errors[0].reason === "invalid_operation",
    "An unknown operation must produce a structured validation error.",
  );
});

it("requires a complete section order", async () => {
  const baseResume = createResume();
  baseResume.sections.push({
    id: "projects",
    kind: "project",
    title: "Projects",
    items: [],
  });
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "partial-reorder",
      title: "Partially reorder sections",
      target: "sections",
      reason: "Exercise complete-order validation.",
      operation: {
        type: "reorder_sections",
        sectionIds: ["projects"],
      },
    },
  ]);

  assert(
    result.errors.length === 1 &&
      result.errors[0].reason === "invalid_operation",
    "A reorder must include every current section exactly once.",
  );
});
