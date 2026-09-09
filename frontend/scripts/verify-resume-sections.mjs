import assert from "node:assert/strict";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const server = await createServer({
  cacheDir: createViteTestCacheDir(),
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  root: process.cwd(),
  server: { hmr: false, middlewareMode: true, ws: false },
  resolve: {
    alias: { "@": new URL("../src", import.meta.url).pathname },
  },
});

try {
  const [sectionModule, sectionMutationModule] = await Promise.all([
    server.ssrLoadModule("/src/lib/resume-sections.ts"),
    server.ssrLoadModule("/src/lib/resume-section-mutations.ts"),
  ]);
  const {
    createResumeSection,
    isCanonicalResumeSection,
    projectResumeSection,
  } = sectionModule;
  const { applySectionMutation } = sectionMutationModule;

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
  const movedEducationItem = applySectionMutation(
    threeEducationItems.sections,
    {
      type: "item.move",
      sectionId: education.id,
      itemId: "education-third",
      direction: "up",
    },
  );
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
    name: "Reseno",
    role: "Maintainer",
    techStack: ["React", "FastAPI"],
    period: "2026",
    url: "https://example.com/reseno",
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
      title: "Reseno",
      subtitle: "Maintainer",
      meta: "React · FastAPI",
      url: "https://example.com/reseno",
    },
    "Preview/PDF projection must retain the semantic project fields.",
  );

  const publication = createResumeSection("publication");
  Object.assign(publication.items[0], {
    title: "How Traceable Feedback Shapes Trust",
    authors: "Ruoan Shen, Maya Li",
    venue: "National HCI Conference",
    date: "2026",
    url: "https://example.com/paper",
    description: "Poster accepted.",
  });
  const renderablePublication = projectResumeSection(publication);
  assert.deepEqual(
    {
      layout: renderablePublication.layout,
      title: renderablePublication.items[0].title,
      subtitle: renderablePublication.items[0].subtitle,
      meta: renderablePublication.items[0].meta,
      period: renderablePublication.items[0].period,
      url: renderablePublication.items[0].url,
      description: renderablePublication.items[0].description,
    },
    {
      layout: "timeline",
      title: "How Traceable Feedback Shapes Trust",
      subtitle: "Ruoan Shen, Maya Li",
      meta: "National HCI Conference",
      period: "2026",
      url: "https://example.com/paper",
      description: "Poster accepted.",
    },
    "Structured publications must retain citation fields in preview and export projection.",
  );
  assert.equal(isCanonicalResumeSection(publication), true);
  assert.equal(
    isCanonicalResumeSection({
      ...publication,
      items: [{ ...publication.items[0], status: "accepted" }],
    }),
    false,
    "Publication items must reject fields outside the canonical citation shape.",
  );

  assert.equal(isCanonicalResumeSection(project), true);
  assert.equal(
    isCanonicalResumeSection({ ...project, id: "project:archive" }),
    false,
    "Section IDs must not contain the evidence reference delimiter.",
  );
  assert.equal(
    isCanonicalResumeSection({
      ...project,
      items: [{ ...project.items[0], id: "project:primary" }],
    }),
    false,
    "Item IDs must not contain the evidence reference delimiter.",
  );
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

  console.log("Resume section V2 domain checks passed.");
} finally {
  await server.close();
}
