import { readFile } from "node:fs/promises";
import { join } from "node:path";
import vm from "node:vm";
import * as ts from "typescript";

const root = new URL("..", import.meta.url).pathname;

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function loadResumeAgentEdits() {
  const source = await readFile(
    join(root, "src", "lib", "resume-agent-edits.ts"),
    "utf8",
  );
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };

  vm.runInNewContext(compiled, {
    exports: module.exports,
    module,
  });

  return module.exports;
}

function createResume() {
  return {
    basic: {
      name: "Original name",
      headline: "Engineer",
      phone: "",
      email: "",
      location: "",
      avatar: "",
      summary: "Original summary",
      customFields: [],
    },
    sections: [
      {
        id: "education",
        kind: "education",
        layout: "timeline",
        customTitle: "Education",
        items: [],
      },
    ],
  };
}

const {
  applyAgentEditsToDraft,
  applyAgentEditsWithMerge,
  createAgentDraftBaseSnapshot,
} = await loadResumeAgentEdits();

{
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
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "skills",
    kind: "skills",
    layout: "list",
    customTitle: "Skills",
    items: [
      {
        id: "skill-1",
        title: "Frontend",
        subtitle: "React, TypeScript",
        meta: "",
        period: "",
        description: "",
        highlights: [],
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
      result.resume.sections[1].items[0].highlights.length === 0,
    "List item updates must preserve the canonical title/subtitle-only shape.",
  );
}

{
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
          kind: "skills",
          layout: "list",
          customTitle: "Skills",
          items: [
            {
              id: "skill-1",
              title: "Frontend",
              subtitle: "",
              meta: "",
              period: "",
              description: "",
              highlights: ["React"],
            },
          ],
        },
      },
    },
  ]);

  assert(
    result.appliedCount === 0 &&
      result.errors.length === 1 &&
      result.errors[0].reason === "invalid_operation",
    "List sections must reject content outside title and subtitle.",
  );
}

{
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
    {
      id: "update-location",
      title: "Update location",
      target: "basic.location",
      reason: "Use the location explicitly supplied by the user.",
      operation: {
        type: "replace_field",
        path: "basic.location",
        value: "Remote",
      },
    },
  ]);

  assert(result.errors.length === 0, "A valid batch must not return errors.");
  assert(result.appliedCount === 3, "A valid batch must commit every edit.");
  assert(result.diffs.length === 3, "A valid batch must expose every diff.");
  assert(
    result.resume.basic.headline === "Staff Engineer" &&
      result.resume.basic.summary === "Updated summary" &&
      result.resume.basic.location === "Remote",
    "A valid batch must return the fully updated resume.",
  );
  assert(
    baseResume.basic.headline === "Engineer" &&
      baseResume.basic.summary === "Original summary" &&
      baseResume.basic.location === "",
    "Applying a batch must never mutate the source resume.",
  );
}

{
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
      },
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
}

{
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
}

{
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
}

{
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
          layout: "timeline",
          customTitle: "Projects",
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
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "projects",
    kind: "project",
    layout: "timeline",
    customTitle: "Projects",
    items: [],
  });
  const currentResume = structuredClone(baseResume);
  currentResume.sections.push({
    id: "skills",
    kind: "skills",
    layout: "list",
    customTitle: "Skills",
    items: [],
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
}

{
  const baseResume = createResume();
  baseResume.sections.push({
    id: "projects",
    kind: "project",
    layout: "timeline",
    customTitle: "Projects",
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
}

{
  const baseResume = createResume();
  const draftBase = createAgentDraftBaseSnapshot(baseResume);
  const edits = [
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
  const generatedDraft = applyAgentEditsWithMerge(
    draftBase,
    baseResume,
    edits,
  );
  const latestResume = structuredClone(baseResume);
  latestResume.basic.name = "User edit after draft generation";
  const appliedDraft = applyAgentEditsWithMerge(
    draftBase,
    latestResume,
    edits,
  );

  assert(
    generatedDraft.resume.basic.summary === "Agent-edited summary",
    "Draft generation must still preview the Agent batch.",
  );
  assert(
    appliedDraft.errors.length === 0 &&
      appliedDraft.resume.basic.name ===
        "User edit after draft generation" &&
      appliedDraft.resume.basic.summary === "Agent-edited summary",
    "Applying a stored draft must rebase onto manual edits made after draft generation.",
  );
}

{
  const baseResume = createResume();
  const draftBase = createAgentDraftBaseSnapshot(baseResume);
  const edits = [
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
  const appliedDraft = applyAgentEditsWithMerge(
    draftBase,
    latestResume,
    edits,
  );

  assert(
    appliedDraft.errors.length === 1 &&
      appliedDraft.errors[0].reason === "conflict",
    "A competing manual edit made after draft generation must reject the draft.",
  );
  assert(
    appliedDraft.appliedCount === 0 &&
      appliedDraft.resume.basic.headline === "Engineer" &&
      appliedDraft.resume.basic.summary ===
        "User edit after draft generation",
    "A late conflict must leave the complete current resume untouched.",
  );
}

console.log("Resume agent edit transaction checks passed.");
