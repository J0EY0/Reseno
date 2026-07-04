import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createServer } from "vite";

const sectionRegistry = JSON.parse(
  readFileSync(
    new URL("../../backend/app/services/agent/section_registry.json", import.meta.url),
    "utf8",
  ),
);

const server = await createServer({
  configFile: false,
  root: process.cwd(),
  server: {
    hmr: false,
    middlewareMode: true,
    ws: false,
  },
  resolve: {
    alias: {
      "@": new URL("../src", import.meta.url).pathname,
    },
  },
});

try {
  const { buildResumeFromPdfLines, textContentToLinesForResumeImport } =
    await server.ssrLoadModule("/src/lib/pdf-resume-import.ts");
  const buildResumeFromLines = (lines, fallbackSectionTitle) =>
    buildResumeFromPdfLines(lines, fallbackSectionTitle, sectionRegistry);

  verifyColumnLineSplitting(textContentToLinesForResumeImport);
  verifyContactLocationExtraction(buildResumeFromLines);
  verifyProjectItemGrouping(buildResumeFromLines);
  verifyFallbackSectionShape(buildResumeFromLines);
  verifyInlineSectionHeading(buildResumeFromLines);
  verifyShortBulletsAndContinuation(buildResumeFromLines);
  verifyAdjacentExperienceItems(buildResumeFromLines);

  console.log("PDF resume import fixtures verified.");
} finally {
  await server.close();
}

function verifyColumnLineSplitting(textContentToLines) {
  const lines = textContentToLines(
    {
      items: [
        textItem("左栏项目", 40, 700),
        textItem("右栏技能", 360, 700),
        textItem("左栏内容", 40, 680),
        textItem("右栏内容", 360, 680),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["左栏项目", "右栏技能", "左栏内容", "右栏内容"],
  );
}

function verifyContactLocationExtraction(buildResumeFromLines) {
  const withLocation = buildResumeFromLines(
    [
      line("王小明", 0),
      line("杭州 | +86 138 0000 0000 | xiaoming@example.com", 1),
      line("教育经历", 2, 14),
      line("浙江大学", 3),
    ],
    "导入内容",
  );
  assert.equal(withLocation.basic.location, "杭州");

  const withHeadline = buildResumeFromLines(
    [
      line("王小明", 0),
      line("前端工程师 | xiaoming@example.com", 1),
      line("教育经历", 2, 14),
      line("浙江大学", 3),
    ],
    "导入内容",
  );
  assert.equal(withHeadline.basic.location, "");
}

function verifyProjectItemGrouping(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("项目经历", 2, 14),
      line("React + TypeScript + Tailwind", 3),
      line("ResuMate", 4),
      line("2026.03 - 至今", 5),
      line("AI Agent 简历制作网站", 6),
      line("• 实现实时编辑、A4 预览、可折叠 section、关键词匹配与 PDF 导出。", 7),
      line("• 将编辑器与真实简历版式拆分为结构化数据模型，渲染更加稳定。", 8),
    ],
    "导入内容",
  );
  const project = resume.sections.find((section) => section.kind === "project");

  assert.equal(project?.items.length, 1);
  assert.equal(project?.items[0]?.title, "ResuMate");
  assert.equal(project?.items[0]?.period, "2026.03 - 至今");
  assert.equal(project?.items[0]?.highlights.length, 2);
}

function verifyFallbackSectionShape(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("+86 138 0000 0000", 2),
      line("个人简介", 3),
      line("保持开头区域不被误判为模块标题", 4),
      line("一段未识别标题", 5, 14),
      line("可以被保留的导入内容", 6),
    ],
    "导入内容",
  );
  const fallback = resume.sections[0];

  assert.equal(fallback?.kind, "other");
  assert.equal(fallback?.layout, "list");
  assert.equal(fallback?.customTitle, "一段未识别标题");
  assert.deepEqual(fallback?.items[0]?.highlights, ["可以被保留的导入内容"]);
}

function verifyInlineSectionHeading(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("技能：能力一、能力二、能力三", 2),
    ],
    "导入内容",
  );
  const skills = resume.sections.find((section) => section.kind === "skills");

  assert.equal(skills?.layout, "list");
  assert.deepEqual(skills?.items[0]?.highlights, ["能力一", "能力二", "能力三"]);
}

function verifyShortBulletsAndContinuation(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("工作经历", 2, 14),
      line("示例公司", 3),
      line("2024.01 - 至今", 4),
      line("示例岗位", 5),
      line("• 负责体验优化", 6),
      line("覆盖核心使用流程", 7),
      line("• 维护编辑器稳定性", 8),
    ],
    "导入内容",
  );
  const work = resume.sections.find((section) => section.kind === "work");

  assert.equal(work?.items.length, 1);
  assert.equal(work?.items[0]?.title, "示例公司");
  assert.equal(work?.items[0]?.subtitle, "示例岗位");
  assert.deepEqual(work?.items[0]?.highlights, [
    "负责体验优化 覆盖核心使用流程",
    "维护编辑器稳定性",
  ]);
}

function verifyAdjacentExperienceItems(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("工作经历", 2, 14),
      line("第一公司", 3),
      line("2023.01 - 2023.12", 4),
      line("第一岗位", 5),
      line("• 完成第一项工作", 6),
      line("第二公司", 7),
      line("2024.01 - 至今", 8),
      line("第二岗位", 9),
      line("• 完成第二项工作", 10),
    ],
    "导入内容",
  );
  const work = resume.sections.find((section) => section.kind === "work");

  assert.equal(work?.items.length, 2);
  assert.equal(work?.items[0]?.title, "第一公司");
  assert.equal(work?.items[1]?.title, "第二公司");
  assert.equal(work?.items[1]?.period, "2024.01 - 至今");
}

function textItem(text, x, y) {
  return {
    str: text,
    transform: [1, 0, 0, 10, x, y],
    width: text.length * 10,
    height: 10,
  };
}

function line(text, index, fontSize = 10) {
  return {
    text,
    page: 1,
    x: 40,
    y: 800 - index * 20,
    fontSize,
  };
}
