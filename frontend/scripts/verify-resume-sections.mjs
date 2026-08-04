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
    projectResumeSection,
  } = await server.ssrLoadModule("/src/lib/resume-sections.ts");

  const education = createResumeSection("education");
  education.id = "education-1";
  education.title = "Academic background";
  education.items[0].school = "Example University";

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
