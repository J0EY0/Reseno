import assert from "node:assert/strict";
import { it } from "vitest";
import { detectPdfResumeDocumentLocale as detectDocumentLocale } from "@/lib/pdf-resume-import/document-language";
import { textContentToLinesForResumeImport as textContentToLines } from "@/lib/pdf-resume-import/pdf-text-extraction";
import {
  buildResumeFromLines,
  line,
  textItem,
  requiredLine,
  requiredSection,
  selectItemFields,
  zhMinimalStructureFixture,
} from "./helpers/pdf-import-fixtures";
it("column line splitting", () => {
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
});

it("duplicate positioned text is deduplicated", () => {
  const duplicate = textItem("重复文本", 40, 700);
  const lines = textContentToLines(
    {
      items: [duplicate, { ...duplicate }],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["重复文本"],
  );
});

it("near duplicate positioned text is deduplicated", () => {
  const lines = textContentToLines(
    {
      items: [
        textItem("重复文本", 40, 700),
        textItem("重复文本", 40.1, 700.1, { width: 40.2 }),
        textItem("重复文本", 40, 680),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["重复文本", "重复文本"],
  );
});

it("rtl text order", () => {
  const lines = textContentToLines(
    {
      items: [
        textItem("مرحبا", 100, 700, { dir: "rtl", width: 40 }),
        textItem("بك", 70, 700, { dir: "rtl", width: 20 }),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["مرحبا بك"],
  );
});

it("mixed direction text order", () => {
  const lines = textContentToLines(
    {
      items: [
        textItem("مرحبا", 100, 700, {
          dir: "rtl",
          width: 40,
        }),
        textItem("2024", 50, 700, {
          dir: "ltr",
          width: 40,
        }),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["مرحبا 2024"],
    "the dominant direction should be weighted by visible text, not token count",
  );
});

it("equal weight mixed direction text order", () => {
  const lines = textContentToLines(
    {
      items: [
        textItem("مرح", 100, 700, {
          dir: "rtl",
          width: 30,
        }),
        textItem("abc", 50, 700, {
          dir: "ltr",
          width: 30,
        }),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["مرح abc"],
    "equal direction weights should follow the first authored token",
  );
});

it("rotated text font size", () => {
  const lines = textContentToLines(
    {
      items: [
        textItem("Rotated", 40, 700, {
          transform: [0, 10, -10, 0, 40, 700],
          height: 0,
        }),
      ],
    },
    1,
  );

  assert.equal(lines[0]?.fontSize, 10);
});

it("retains the dominant text font for structural heading recognition", () => {
  const lines = textContentToLines(
    {
      items: [
        textItem("•", 30, 700, { width: 4, fontName: "symbol" }),
        textItem("Community Involvement", 40, 700, {
          fontName: "heading",
        }),
        textItem("Supported community workshops.", 40, 680, {
          fontName: "body",
        }),
      ],
    },
    1,
  );

  assert.equal(lines[0]?.fontName, "heading");
  assert.equal(lines[1]?.fontName, "body");
});

it("continuous han glyph tokens", () => {
  const lines = textContentToLines(
    {
      items: ["禰\u{E0100}", ..."续中文"].map((character, index) => ({
        ...textItem(character, 40 + index * 10, 700),
        width: 8,
      })),
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["禰\u{E0100}续中文"],
  );
});

it("document language detection", () => {
  assert.equal(
    detectDocumentLocale([
      line("Élodie Martin", 0),
      line("Expérience professionnelle", 1),
    ]),
    "en",
    "accented Latin letters should remain an English document",
  );
  assert.equal(
    detectDocumentLocale([line("王小明", 0), line("Software Engineer", 1)]),
    "zh",
    "mixed Han and Latin text should default to Chinese",
  );
  assert.equal(
    detectDocumentLocale([
      line("Иван Петров", 0),
      line("Software Engineer", 1),
    ]),
    "en",
    "a non-Chinese script should use the non-Chinese document locale",
  );
  assert.equal(
    detectDocumentLocale([line("Resume", 0)]),
    "en",
    "all-Latin text should be classified as English after import text validation",
  );
});

it("zh minimal structure regression", () => {
  // Keep selected PDF.js token boundaries and x/y coordinates from the source
  // PDF. Flattened, hand-ordered strings cannot reproduce same-row right
  // metadata or compatibility ideographs emitted by the original PDF font.
  const lines = textContentToLines(
    zhMinimalStructureFixture,
    zhMinimalStructureFixture.page,
  );
  const resume = buildResumeFromLines(lines, "导入内容");

  assert.equal(detectDocumentLocale(lines), "zh");

  for (const section of resume.sections.filter(
    (candidate) => candidate.kind === "simple_list",
  )) {
    for (const item of section.items) {
      assert.deepEqual(
        Object.keys(item).sort(),
        ["content", "id"],
        "simple-list imports must use only their semantic content field",
      );
    }
  }

  assert.ok(
    lines.some((line) => line.text === "项目经历"),
    "CJK compatibility ideographs in 项⽬经历 should normalize before parsing",
  );
  assert.ok(
    lines.some((line) => /^语言[:：]/.test(line.text)),
    "CJK compatibility ideographs in 语⾔ should normalize before parsing",
  );

  const companyLine = requiredLine(lines, "腾讯");
  const businessLine = requiredLine(lines, "企业协同产品线");
  assert.ok(
    Math.abs(companyLine.y - businessLine.y) <= 2,
    "company and business line should remain on the same visual row",
  );
  assert.ok(
    companyLine.x < businessLine.x,
    "same-row fields should preserve their left-to-right x order",
  );

  const education = requiredSection(resume, "education");
  assert.equal(education.items.length, 1);
  assert.deepEqual(selectItemFields(education.items[0]), {
    title: "浙江大学",
    subtitle: "计算机科学与技术 本科",
    meta: "GPA 3.85 / 4.0",
    period: "2019.09 - 2023.06",
    description: "主修前端工程、数据结构、软件工程与机器学习相关课程。",
    highlights: ["获得校一等奖学金。", "毕业设计围绕智能内容生成工具展开。"],
  });

  const internship = requiredSection(resume, "internship");
  assert.equal(internship.items.length, 1);
  assert.deepEqual(selectItemFields(internship.items[0]), {
    title: "腾讯",
    subtitle: "前端开发实习生",
    meta: "企业协同产品线",
    period: "2022.07 - 2022.09",
    description: "参与后台管理系统和内容编辑器的体验优化。",
    highlights: [
      "负责编辑器表单模块重构，页面状态管理复杂度显著下降。",
      "联动设计与测试完善交互细节，减少线上样式回归问题。",
    ],
  });

  const project = requiredSection(resume, "project");
  assert.equal(project.items.length, 1);
  assert.deepEqual(selectItemFields(project.items[0]), {
    title: "Reseno",
    subtitle: "AI Agent 简历制作网站",
    meta: "React · TypeScript · Tailwind · shadcn/ui",
    period: "2026.03 - 至今",
    description:
      "实现实时编辑、A4 预览、可折叠 section、关键词匹配与 PDF 导出。",
    highlights: [
      "将编辑器与真实简历版式拆分为结构化数据模型，渲染更加稳定。",
      "通过 AI Copilot 对 JD 关键词进行识别，并提供简历内容增强建议。",
    ],
  });

  const other = requiredSection(resume, "other");
  assert.equal(other.items.length, 1);
  assert.equal(
    other.items[0].content,
    "<ul><li>技能：React、TypeScript、Node.js、Prompt Engineering</li><li>语言：英语 CET-6（544），雅思 6.5</li></ul>",
  );

  assert.equal(resume.basic.name, "王小明");
  assert.equal(resume.basic.headline, "前端开发工程师 / AI 应用方向");
  assert.equal(resume.basic.phone, "+86 138 0000 0000");
  assert.equal(resume.basic.email, "xiaoming@example.com");
  assert.equal(resume.basic.location, "杭州");
  assert.equal(
    resume.basic.summary,
    "关注 AI Agent 与简历工作流产品，熟悉 React、TypeScript 与实时渲染，能够将复杂编辑体验整理为结构清晰、适合导出的简历页面。",
  );
  assert.deepEqual(
    resume.basic.customFields.map(({ label, value, type }) => ({
      label,
      value,
      type,
    })),
    [
      {
        label: "GitHub",
        value: "github.com/xiaoming",
        type: "url",
      },
      {
        label: "作品集",
        value: "www.xiaoming.dev",
        type: "url",
      },
    ],
  );
});
