import assert from "node:assert/strict";
import { createServer } from "vite";

const server = await createServer({
  configFile: false,
  root: process.cwd(),
  server: { hmr: false, middlewareMode: true, ws: false },
  resolve: {
    alias: { "@": new URL("../src", import.meta.url).pathname },
  },
});

try {
  const {
    applySectionMutation,
    createResumeSection,
    isCanonicalResumeData,
    isCanonicalResumeSection,
    parseCommaSeparatedItems,
    projectResumeSection,
  } = await server.ssrLoadModule("/src/lib/resume-sections.ts");

  assert.deepEqual(
    parseCommaSeparatedItems("React, TypeScript， FastAPI, "),
    ["React", "TypeScript", "FastAPI"],
    "Comma-separated fields must publish canonical values while the user types.",
  );

  const education = createResumeSection("education");
  education.id = "education-1";
  education.title = "Academic background";
  education.items[0].school = "Example University";
  education.items[0].degree = "B.Sc.";
  education.items[0].major = "Computer Science";

  const addedEducationItem = applySectionMutation([education], {
    type: "item.add",
    sectionId: education.id,
    itemId: "education-new",
  });
  assert.equal(addedEducationItem.status, "applied");
  assert.equal(
    addedEducationItem.sections[0].items.at(-1)?.id,
    "education-new",
    "An interactive add must retain its caller-generated id so only that item opens.",
  );
  const threeEducationItems = applySectionMutation(
    addedEducationItem.sections,
    {
      type: "item.add",
      sectionId: education.id,
      itemId: "education-third",
    },
  );
  const movedEducationItem = applySectionMutation(threeEducationItems.sections, {
    type: "item.move",
    sectionId: education.id,
    itemId: "education-third",
    direction: "up",
  });
  assert.equal(movedEducationItem.status, "applied");
  assert.deepEqual(
    movedEducationItem.sections[0].items.map((item) => item.id),
    [education.items[0].id, "education-third", "education-new"],
    "Entry ordering must be changed atomically within its section.",
  );
  const boundaryMove = applySectionMutation(movedEducationItem.sections, {
    type: "item.move",
    sectionId: education.id,
    itemId: education.items[0].id,
    direction: "up",
  });
  assert.equal(boundaryMove.status, "unchanged");
  assert.equal(boundaryMove.sections, movedEducationItem.sections);

  const duplicateAdd = applySectionMutation(movedEducationItem.sections, {
    type: "item.add",
    sectionId: education.id,
    itemId: education.items[0].id,
  });
  assert.equal(duplicateAdd.status, "rejected");
  assert.equal(duplicateAdd.code, "ITEM_ID_CONFLICT");

  const restoredItem = movedEducationItem.sections[0].items[0];
  const removedForAutosave = applySectionMutation(movedEducationItem.sections, {
    type: "item.remove",
    sectionId: education.id,
    itemId: restoredItem.id,
  });
  const persistedDeletion = structuredClone(removedForAutosave.sections);
  const restoredAfterAutosave = applySectionMutation(persistedDeletion, {
    type: "item.restore",
    sectionId: education.id,
    sectionKind: "education",
    item: restoredItem,
    index: 0,
  });
  assert.equal(restoredAfterAutosave.status, "applied");
  assert.deepEqual(
    restoredAfterAutosave.sections[0].items.map((item) => item.id),
    movedEducationItem.sections[0].items.map((item) => item.id),
    "Undo must restore the original item and position after deletion was autosaved.",
  );
  assert.deepEqual(
    restoredAfterAutosave.sections[0].items[0],
    restoredItem,
    "Undo must preserve every field from the deleted item snapshot.",
  );

  const duplicateRestore = applySectionMutation(
    restoredAfterAutosave.sections,
    {
      type: "item.restore",
      sectionId: education.id,
      sectionKind: "education",
      item: restoredItem,
      index: 0,
    },
  );
  assert.equal(duplicateRestore.status, "rejected");
  assert.equal(duplicateRestore.code, "ITEM_ID_CONFLICT");

  const wrongKindRestore = applySectionMutation(persistedDeletion, {
    type: "item.restore",
    sectionId: education.id,
    sectionKind: "project",
    item: {
      id: "wrong-kind",
      name: "Wrong kind",
      role: "",
      techStack: [],
      period: "",
      url: "",
      description: "",
      highlights: [],
    },
    index: 0,
  });
  assert.equal(wrongKindRestore.status, "rejected");
  assert.equal(wrongKindRestore.code, "SECTION_KIND_MISMATCH");

  const invalidRestore = applySectionMutation(persistedDeletion, {
    type: "item.restore",
    sectionId: education.id,
    sectionKind: "education",
    item: { id: "invalid-item" },
    index: 0,
  });
  assert.equal(invalidRestore.status, "rejected");
  assert.equal(invalidRestore.code, "INVALID_ITEM");

  const clampedRestore = applySectionMutation(persistedDeletion, {
    type: "item.restore",
    sectionId: education.id,
    sectionKind: "education",
    item: { ...restoredItem, id: "clamped-item" },
    index: Number.POSITIVE_INFINITY,
  });
  assert.equal(clampedRestore.status, "applied");
  assert.equal(
    clampedRestore.sections[0].items.at(-1)?.id,
    "clamped-item",
    "A non-finite or oversized restore index must clamp to the section end.",
  );

  const educationSections = [education];
  const kindMismatch = applySectionMutation(educationSections, {
    type: "item.update",
    sectionId: education.id,
    sectionKind: "project",
    itemId: education.items[0].id,
    patch: { name: "Must not be written" },
  });
  assert.equal(kindMismatch.status, "rejected");
  assert.equal(kindMismatch.code, "SECTION_KIND_MISMATCH");
  assert.equal(
    kindMismatch.sections,
    educationSections,
    "A stale editor must not partially modify a section of another kind.",
  );

  const simpleList = createResumeSection("simple_list");
  simpleList.id = "skills";
  simpleList.items[0].content = "<ul><li>React</li><li>TypeScript</li></ul>";

  for (const mutation of [
    { type: "item.add", sectionId: simpleList.id },
    {
      type: "item.remove",
      sectionId: simpleList.id,
      itemId: simpleList.items[0].id,
    },
    {
      type: "item.move",
      sectionId: simpleList.id,
      itemId: simpleList.items[0].id,
      direction: "up",
    },
    {
      type: "item.restore",
      sectionId: simpleList.id,
      sectionKind: "simple_list",
      item: simpleList.items[0],
      index: 0,
    },
  ]) {
    const result = applySectionMutation([simpleList], mutation);
    assert.equal(result.status, "rejected");
    assert.equal(result.code, "SIMPLE_LIST_CARDINALITY");
    assert.equal(
      result.sections[0],
      simpleList,
      "A simple-list section must always retain its sole rich-text item.",
    );
  }

  assert.equal(isCanonicalResumeSection(simpleList), true);
  assert.equal(
    isCanonicalResumeSection({ ...simpleList, items: [] }),
    false,
    "A simple-list section without its rich-text item is invalid.",
  );
  assert.equal(
    isCanonicalResumeSection({
      ...simpleList,
      items: [...simpleList.items, { id: "skill-2", content: "Python" }],
    }),
    false,
    "A simple-list section cannot contain multiple independently editable items.",
  );

  const project = createResumeSection("project");
  Object.assign(project.items[0], {
    name: "ResuMate",
    role: "Maintainer",
    techStack: ["React", "FastAPI"],
    period: "2026",
    url: "https://example.com/resumate",
    description: "Semantic resume editor",
    highlights: ["<ul><li>Stable V2 model</li></ul>"],
  });
  const renderable = projectResumeSection(project);
  assert.deepEqual(
    {
      layout: renderable.layout,
      title: renderable.items[0].title,
      subtitle: renderable.items[0].subtitle,
      meta: renderable.items[0].meta,
      url: renderable.items[0].url,
    },
    {
      layout: "timeline",
      title: "ResuMate",
      subtitle: "Maintainer",
      meta: "React · FastAPI",
      url: "https://example.com/resumate",
    },
    "Preview/PDF projection must retain the semantic project fields.",
  );

  assert.equal(isCanonicalResumeSection(project), true);
  assert.equal(
    isCanonicalResumeSection({
      id: "legacy",
      kind: "project",
      layout: "timeline",
      customTitle: "Projects",
      items: [],
    }),
    false,
    "Legacy generic sections must not silently enter the V2 model.",
  );

  const document = {
    schemaVersion: 2,
    basic: {
      name: "",
      headline: "",
      phone: "",
      email: "",
      location: "",
      avatar: "",
      summary: "",
      customFields: [],
    },
    sections: [project],
  };
  assert.equal(isCanonicalResumeData(document), true);
  assert.equal(
    isCanonicalResumeData({ ...document, schemaVersion: 1 }),
    false,
    "The frontend import boundary must reject non-V2 documents.",
  );
  assert.equal(
    isCanonicalResumeData({
      ...document,
      sections: [project, { ...project, id: "duplicate-section" }],
    }),
    false,
    "The frontend must reject duplicate item identities before autosave.",
  );

  console.log("Resume section V2 domain checks passed.");
} finally {
  await server.close();
}
