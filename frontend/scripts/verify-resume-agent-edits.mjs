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

const { applyAgentEditsToDraft, applyAgentEditsWithMerge } =
  await loadResumeAgentEdits();

{
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "rename",
      title: "Rename candidate",
      target: "basic.name",
      reason: "Use the requested name.",
      operation: {
        type: "replace_field",
        path: "basic.name",
        value: "Updated name",
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
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "rename",
      title: "Rename candidate",
      target: "basic.name",
      reason: "Use the requested name.",
      operation: {
        type: "replace_field",
        path: "basic.name",
        value: "Updated name",
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
    result.resume.basic.name === "Updated name" &&
      result.resume.basic.summary === "Updated summary",
    "A valid batch must return the fully updated resume.",
  );
  assert(
    baseResume.basic.name === "Original name" &&
      baseResume.basic.summary === "Original summary",
    "Applying a batch must never mutate the source resume.",
  );
}

{
  const baseResume = createResume();
  const result = applyAgentEditsToDraft(baseResume, [
    {
      id: "rename",
      title: "Rename candidate",
      target: "basic.name",
      reason: "Use the requested name.",
      operation: {
        type: "replace_field",
        path: "basic.name",
        value: "Updated name",
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
    result.appliedCount === 0 && result.resume.basic.name === "Original name",
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

console.log("Resume agent edit transaction checks passed.");
