import assert from "node:assert/strict";
import { it } from "vitest";
import { buildResumeFromPdfLines } from "@/lib/pdf-resume-import/parser";
import {
  line,
  resumeImportLexicon,
  sectionRegistry,
} from "./helpers/pdf-import-fixtures";

const parse = (lines: Parameters<typeof buildResumeFromPdfLines>[0]) =>
  buildResumeFromPdfLines(lines, "Other", sectionRegistry, resumeImportLexicon);

it.each([
  ["教育背景", "志愿服务与社区活动", "示例大学", "参与社区志愿活动。"],
  [
    "Education",
    "Community Service and Volunteering",
    "Example University",
    "Supported community workshops.",
  ],
])(
  "learns modest heading sizes from the document: %s",
  (heading, unknown, school, body) => {
    const result = parse([
      line("Example Person", 0, 22),
      line("person@example.com", 1, 10.5),
      line(heading, 2, 12),
      line(school, 3, 10.5),
      line("2020 - 2024", 4, 10.5),
      line(unknown, 5, 12),
      line(body, 6, 10.5),
    ]);
    assert.deepEqual(
      result.resume.sections.map(({ kind, title }) => ({ kind, title })),
      [
        { kind: "education", title: heading },
        { kind: "simple_list", title: unknown },
      ],
    );
    assert.equal(result.unclassifiedLineCount, 1);
    assert.doesNotMatch(
      JSON.stringify(result.resume.sections[0]),
      new RegExp(unknown),
    );
  },
);

it("uses recurring font styles when headings and body share a size", () => {
  const result = parse([
    { ...line("Example Person", 0, 22), fontName: "display" },
    { ...line("person@example.com", 1), fontName: "body" },
    { ...line("Education", 2), fontName: "heading" },
    { ...line("Example University", 3), fontName: "body" },
    { ...line("2020 - 2024", 4), fontName: "body" },
    { ...line("Community Involvement", 5), fontName: "heading" },
    { ...line("Supported community workshops.", 6), fontName: "body" },
  ]);
  assert.equal(result.resume.sections.length, 2);
  assert.equal(result.resume.sections[1]?.title, "Community Involvement");
});

it("recognizes consistent heading sizes across different embedded font subsets", () => {
  const result = parse([
    { ...line("示例同学", 0, 22), fontName: "display" },
    { ...line("person@example.com", 1, 10.5), fontName: "body" },
    { ...line("教育背景", 2, 12), fontName: "subset-education" },
    { ...line("示例大学", 3, 10.5), fontName: "body" },
    { ...line("2020 - 2024", 4, 10.5), fontName: "body" },
    { ...line("研究活动", 5, 12), fontName: "subset-research" },
    { ...line("参与社区文档结构识别研究。", 6, 10.5), fontName: "body" },
  ]);
  assert.deepEqual(
    result.resume.sections.map(({ title }) => title),
    ["教育背景", "研究活动"],
  );
});

it("recognizes bilingual headings without replacing their source language", () => {
  const result = parse([
    line("Example Person", 0, 22),
    line("person@example.com", 1),
    line("教育背景 / Education", 2),
    line("Example University", 3),
    line("2020 - 2024", 4),
    line("Projects（项目经历）", 5),
    line("Example Project", 6),
    line("2024 - Present", 7),
    line("• Built a useful tool.", 8),
  ]);
  assert.deepEqual(
    result.resume.sections.map(({ kind, title }) => ({ kind, title })),
    [
      { kind: "education", title: "教育背景 / Education" },
      { kind: "project", title: "Projects（项目经历）" },
    ],
  );
});

it.each([
  ["教育背景", "技术能力", "项目实践", "荣誉奖励"],
  ["教育背景", "技術能力", "專案經歷", "榮譽獎項"],
  [
    "Academic Background",
    "Technical Expertise",
    "Project Work",
    "Honors and Awards",
  ],
])(
  "recognizes translated section vocabulary: %s",
  (education, skills, projects, awards) => {
    const result = parse([
      line("Example Person", 0, 22),
      line("person@example.com", 1),
      line(education, 2),
      line("Example University", 3),
      line("2020 - 2024", 4),
      line(skills, 5),
      line("Python, TypeScript", 6),
      line(projects, 7),
      line("Example Project", 8),
      line("2024 - Present", 9),
      line("• Built a useful tool.", 10),
      line(awards, 11),
      line("Example Award", 12),
    ]);
    assert.deepEqual(
      result.resume.sections.map(({ kind }) => kind),
      ["education", "simple_list", "project", "achievement"],
    );
  },
);

it("does not turn body labels or prominent dated employers into sections", () => {
  const result = parse([
    line("Example Person", 0, 22),
    line("person@example.com", 1),
    line("Experience", 2, 12),
    line("First Company", 3),
    line("2020 - 2022", 4),
    line("• Built a service.", 5),
    line("Second Company", 6, 12),
    line("2022 - Present", 7),
    line("• Improved the service.", 8),
    line("Tools and languages: Python, TypeScript", 9),
  ]);
  assert.equal(result.resume.sections.length, 1);
  assert.equal(result.resume.sections[0]?.items.length, 2);
});

it("keeps undated bold project names within Projects when section headings use the same font", () => {
  const result = parse([
    { ...line("Example Person", 0, 22), fontName: "display" },
    { ...line("person@example.com", 1), fontName: "body" },
    { ...line("Projects", 2), fontName: "bold" },
    { ...line("Document Workspace", 3), fontName: "bold" },
    {
      ...line("Built accessible editing and review workflows.", 4),
      fontName: "body",
    },
    { ...line("Improved team collaboration.", 5), fontName: "body" },
    { ...line("Data Explorer", 6), fontName: "bold" },
    {
      ...line("Delivered interactive data visualization tools.", 7),
      fontName: "body",
    },
    { ...line("Community Involvement", 8, 12), fontName: "bold" },
    { ...line("Supported community workshops.", 9), fontName: "body" },
  ]);

  assert.deepEqual(
    result.resume.sections.map(({ kind, title }) => ({ kind, title })),
    [
      { kind: "project", title: "Projects" },
      { kind: "simple_list", title: "Community Involvement" },
    ],
  );
  const projects = result.resume.sections[0];
  assert.equal(projects.kind, "project");
  if (projects.kind !== "project") throw new Error("Expected projects");
  assert.deepEqual(
    projects.items.map(({ name }) => name),
    ["Document Workspace", "Data Explorer"],
  );
  assert.match(projects.items[0].description, /editing and review/);
  assert.match(projects.items[1].description, /data visualization/);
});

it.each([
  ["Experience", "experience", "First Company", "Second Company"],
  ["Education", "education", "Example University", "Other University"],
  ["Awards", "achievement", "Research Prize", "Community Award"],
  [
    "Publications",
    "publication",
    "Reliable Document Analysis",
    "Accessible Document Systems",
  ],
] as const)(
  "preserves undated items and all their content within %s",
  (heading, kind, first, second) => {
    const firstBody = "Contributed to accessible document research.";
    const secondBody = "Improved collaboration across distributed teams.";
    const result = parse([
      { ...line("Example Person", 0, 22), fontName: "display" },
      { ...line("person@example.com", 1), fontName: "body" },
      { ...line(heading, 2), fontName: "bold" },
      { ...line(first, 3), fontName: "bold" },
      { ...line(firstBody, 4), fontName: "body" },
      { ...line(second, 5), fontName: "bold" },
      { ...line(secondBody, 6), fontName: "body" },
      { ...line("Community Involvement", 7, 12), fontName: "bold" },
      { ...line("Supported community workshops.", 8), fontName: "body" },
    ]);

    assert.deepEqual(
      result.resume.sections.map(({ kind, title }) => ({ kind, title })),
      [
        { kind, title: heading },
        { kind: "simple_list", title: "Community Involvement" },
      ],
    );
    const items = JSON.stringify(result.resume.sections[0].items);
    for (const text of [first, firstBody, second, secondBody]) {
      assert.ok(items.includes(text), `Missing content: ${text}`);
    }
  },
);
