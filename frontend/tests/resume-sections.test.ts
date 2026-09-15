// @vitest-environment node
import assert from "node:assert/strict";
import { expect, it } from "vitest";

import {
  applySectionMutation,
  type ResumeSectionMutation,
} from "@/lib/resume-section-mutations";
import {
  createResumeSection,
  isCanonicalResumeSection,
  projectResumeSection,
} from "@/lib/resume-sections";

function educationSection(id = "education-1", itemCount = 1) {
  const section = createResumeSection("education");
  assert(section.kind === "education");
  section.id = id;
  section.title = "Academic background";
  section.items[0].id = `${id}-item`;
  section.items[0].school = "Example University";
  section.items[0].degree = "B.Sc.";
  section.items[0].major = "Computer Science";
  for (const itemId of ["education-new", "education-third"].slice(
    0,
    itemCount - 1,
  )) {
    const empty = createResumeSection("education");
    assert(empty.kind === "education");
    section.items.push({ ...empty.items[0], id: itemId });
  }
  return section;
}

function reorderFixture() {
  const section = educationSection("education-1", 3);
  const otherEducation = createResumeSection("education");
  otherEducation.id = "education-other";
  otherEducation.items[0].id = "education-other-item";
  section.items.forEach(Object.freeze);
  Object.freeze(section.items);
  Object.freeze(section);
  const sections = [section, otherEducation];
  Object.freeze(sections);
  return {
    section,
    otherEducation,
    sections,
    snapshot: structuredClone(sections),
  };
}

it("adds caller-owned item IDs, moves atomically and preserves boundary no-ops", () => {
  const education = educationSection();
  const added = applySectionMutation([education], {
    type: "item.add",
    sectionId: education.id,
    itemId: "education-new",
  });
  expect(added.status).toBe("applied");
  expect(added.sections[0].items.at(-1)?.id).toBe("education-new");
  const three = applySectionMutation(added.sections, {
    type: "item.add",
    sectionId: education.id,
    itemId: "education-third",
  });
  const moved = applySectionMutation(three.sections, {
    type: "item.move",
    sectionId: education.id,
    itemId: "education-third",
    direction: "up",
  });
  expect(moved.status).toBe("applied");
  expect(moved.sections[0].items.map((item) => item.id)).toStrictEqual([
    education.items[0].id,
    "education-third",
    "education-new",
  ]);
  const boundary = applySectionMutation(moved.sections, {
    type: "item.move",
    sectionId: education.id,
    itemId: education.items[0].id,
    direction: "up",
  });
  expect(boundary.status).toBe("unchanged");
  expect(boundary.sections).toBe(moved.sections);
  expect(
    applySectionMutation(moved.sections, {
      type: "item.add",
      sectionId: education.id,
      itemId: education.items[0].id,
    }),
  ).toMatchObject({ status: "rejected", code: "ITEM_ID_CONFLICT" });
});

it.each([
  [0, 2, [1, 2, 0]],
  [2, 0, [2, 0, 1]],
] as const)(
  "reorders item %i onto %i without mutating inputs or replacing items",
  (from, to, order) => {
    const { section, otherEducation, sections, snapshot } = reorderFixture();
    const result = applySectionMutation(sections, {
      type: "item.reorder",
      sectionId: section.id,
      sectionKind: "education",
      itemId: section.items[from].id,
      overId: section.items[to].id,
    });
    expect(result.status).toBe("applied");
    expect(result.sections[0].items.map((item) => item.id)).toStrictEqual(
      order.map((index) => section.items[index].id),
    );
    order.forEach((originalIndex, index) => {
      expect(result.sections[0].items[index]).toBe(
        section.items[originalIndex],
      );
    });
    expect(result.sections[1]).toBe(otherEducation);
    expect(sections).toStrictEqual(snapshot);
  },
);

it("keeps the original sections when an item is dropped onto itself", () => {
  const { section, sections } = reorderFixture();
  const result = applySectionMutation(sections, {
    type: "item.reorder",
    sectionId: section.id,
    sectionKind: "education",
    itemId: section.items[0].id,
    overId: section.items[0].id,
  });
  expect(result.status).toBe("unchanged");
  expect(result.sections).toBe(sections);
});

it.each([
  [{ sectionId: "missing-section" }, "SECTION_NOT_FOUND"],
  [{ sectionKind: "project" }, "SECTION_KIND_MISMATCH"],
  [{ itemId: "missing-item" }, "ITEM_NOT_FOUND"],
  [{ overId: "missing-item" }, "ITEM_NOT_FOUND"],
  [{ itemId: "missing-item", overId: "missing-item" }, "ITEM_NOT_FOUND"],
  [{ itemId: "education-other-item" }, "ITEM_NOT_FOUND"],
  [{ overId: "education-other-item" }, "ITEM_NOT_FOUND"],
] as const)(
  "rejects a stale or cross-section item drop %j with %s",
  (patch, code) => {
    const { section, sections, snapshot } = reorderFixture();
    const result = applySectionMutation(sections, {
      type: "item.reorder",
      sectionId: section.id,
      sectionKind: "education",
      itemId: section.items[0].id,
      overId: section.items[2].id,
      ...patch,
    });
    expect(result).toMatchObject({ status: "rejected", code });
    expect(result.sections).toBe(sections);
    expect(sections).toStrictEqual(snapshot);
  },
);

it.each([
  [0, 2, [1, 2, 0]],
  [2, 0, [2, 0, 1]],
] as const)(
  "reorders section %i onto %i while retaining section identities",
  (from, to, order) => {
    const { section, otherEducation } = reorderFixture();
    const project = createResumeSection("project");
    project.id = "project-reorder";
    const sections = [section, otherEducation, project];
    Object.freeze(sections);
    const snapshot = structuredClone(sections);
    const result = applySectionMutation(sections, {
      type: "section.reorder",
      sectionId: sections[from].id,
      overId: sections[to].id,
    });
    expect(result.status).toBe("applied");
    expect(result.sections.map((entry) => entry.id)).toStrictEqual(
      order.map((index) => sections[index].id),
    );
    order.forEach((originalIndex, index) =>
      expect(result.sections[index]).toBe(sections[originalIndex]),
    );
    expect(sections).toStrictEqual(snapshot);
  },
);

it.each([
  ["education-1", "education-1", "unchanged"],
  ["missing-section", "education-other", "rejected"],
  ["education-other", "missing-section", "rejected"],
  ["missing-section", "missing-section", "rejected"],
] as const)(
  "handles section drop %s onto %s as %s",
  (sectionId, overId, status) => {
    const { section, otherEducation } = reorderFixture();
    const project = createResumeSection("project");
    project.id = "project-reorder";
    const sections = [section, otherEducation, project];
    Object.freeze(sections);
    const snapshot = structuredClone(sections);
    const result = applySectionMutation(sections, {
      type: "section.reorder",
      sectionId,
      overId,
    });
    expect(result.status).toBe(status);
    if (status === "rejected")
      expect(result).toHaveProperty("code", "SECTION_NOT_FOUND");
    expect(result.sections).toBe(sections);
    expect(sections).toStrictEqual(snapshot);
  },
);

it("restores an autosaved deletion with all fields and original position, rejecting invalid restores", () => {
  const education = educationSection("education-1", 3);
  [education.items[1], education.items[2]] = [
    education.items[2],
    education.items[1],
  ];
  const item = education.items[0];
  const removed = applySectionMutation([education], {
    type: "item.remove",
    sectionId: education.id,
    itemId: item.id,
  });
  const persisted = structuredClone(removed.sections);
  const restore = {
    type: "item.restore",
    sectionId: education.id,
    sectionKind: "education",
    item,
    index: 0,
  } as const;
  const restored = applySectionMutation(persisted, restore);
  expect(restored.status).toBe("applied");
  expect(restored.sections[0].items.map((entry) => entry.id)).toStrictEqual(
    education.items.map((entry) => entry.id),
  );
  expect(restored.sections[0].items[0]).toStrictEqual(item);
  expect(applySectionMutation(restored.sections, restore)).toMatchObject({
    status: "rejected",
    code: "ITEM_ID_CONFLICT",
  });
  expect(
    applySectionMutation(persisted, {
      ...restore,
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
    }),
  ).toMatchObject({ status: "rejected", code: "SECTION_KIND_MISMATCH" });
  expect(
    applySectionMutation(persisted, {
      ...restore,
      item: { id: "invalid-item" },
    } as ResumeSectionMutation),
  ).toMatchObject({ status: "rejected", code: "INVALID_ITEM" });
  const clamped = applySectionMutation(persisted, {
    ...restore,
    item: { ...item, id: "clamped-item" },
    index: Number.POSITIVE_INFINITY,
  });
  expect(clamped.status).toBe("applied");
  expect(clamped.sections[0].items.at(-1)?.id).toBe("clamped-item");
});

it("rejects stale editors targeting the wrong section kind without replacing sections", () => {
  const education = educationSection();
  const sections = [education];
  const result = applySectionMutation(sections, {
    type: "item.update",
    sectionId: education.id,
    sectionKind: "project",
    itemId: education.items[0].id,
    patch: { name: "Must not be written" },
  });
  expect(result).toMatchObject({
    status: "rejected",
    code: "SECTION_KIND_MISMATCH",
  });
  expect(result.sections).toBe(sections);
});

it("keeps the sole simple-list rich-text item across all cardinality-changing mutations", () => {
  const section = createResumeSection("simple_list");
  assert(section.kind === "simple_list");
  section.id = "skills";
  section.items[0].content = "<ul><li>React</li><li>TypeScript</li></ul>";
  const item = section.items[0];
  const mutations: ResumeSectionMutation[] = [
    { type: "item.add", sectionId: section.id },
    { type: "item.remove", sectionId: section.id, itemId: item.id },
    {
      type: "item.move",
      sectionId: section.id,
      itemId: item.id,
      direction: "up",
    },
    {
      type: "item.reorder",
      sectionId: section.id,
      sectionKind: "simple_list",
      itemId: item.id,
      overId: item.id,
    },
    {
      type: "item.restore",
      sectionId: section.id,
      sectionKind: "simple_list",
      item,
      index: 0,
    },
  ];
  for (const mutation of mutations) {
    const result = applySectionMutation([section], mutation);
    expect(result).toMatchObject({
      status: "rejected",
      code: "SIMPLE_LIST_CARDINALITY",
    });
    expect(result.sections[0]).toBe(section);
  }
  expect(isCanonicalResumeSection(section)).toBe(true);
  expect(isCanonicalResumeSection({ ...section, items: [] })).toBe(false);
  expect(
    isCanonicalResumeSection({
      ...section,
      items: [...section.items, { id: "skill-2", content: "Python" }],
    }),
  ).toBe(false);
});

it("projects project and publication fields while enforcing canonical section shapes", () => {
  const project = createResumeSection("project");
  assert(project.kind === "project");
  Object.assign(project.items[0], {
    name: "Reseno",
    role: "Maintainer",
    techStack: ["React", "FastAPI"],
    period: "2026",
    url: "https://example.com/reseno",
    description: "Semantic resume editor",
    highlights: ["<ul><li>Stable V2 model</li></ul>"],
  });
  const projected = projectResumeSection(project);
  expect(projected.layout).toBe("timeline");
  expect(projected.items[0]).toMatchObject({
    title: "Reseno",
    subtitle: "Maintainer",
    meta: "React · FastAPI",
    url: "https://example.com/reseno",
  });
  const publication = createResumeSection("publication");
  assert(publication.kind === "publication");
  Object.assign(publication.items[0], {
    title: "How Traceable Feedback Shapes Trust",
    authors: "Ruoan Shen, Maya Li",
    venue: "National HCI Conference",
    date: "2026",
    url: "https://example.com/paper",
    description: "Poster accepted.",
  });
  const citation = projectResumeSection(publication);
  expect(citation.layout).toBe("timeline");
  expect(citation.items[0]).toMatchObject({
    title: "How Traceable Feedback Shapes Trust",
    subtitle: "Ruoan Shen, Maya Li",
    meta: "National HCI Conference",
    period: "2026",
    url: "https://example.com/paper",
    description: "Poster accepted.",
  });
  expect(isCanonicalResumeSection(publication)).toBe(true);
  expect(
    isCanonicalResumeSection({
      ...publication,
      items: [{ ...publication.items[0], status: "accepted" }],
    }),
  ).toBe(false);
  expect(isCanonicalResumeSection(project)).toBe(true);
  expect(isCanonicalResumeSection({ ...project, id: "project:archive" })).toBe(
    false,
  );
  expect(
    isCanonicalResumeSection({
      ...project,
      items: [{ ...project.items[0], id: "project:primary" }],
    }),
  ).toBe(false);
  expect(
    isCanonicalResumeSection({
      id: "legacy",
      kind: "project",
      layout: "timeline",
      customTitle: "Projects",
      items: [],
    }),
  ).toBe(false);
});
