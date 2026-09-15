import assert from "node:assert/strict";
import { it } from "vitest";
import { countTextGraphemes } from "@/lib/pdf-resume-import/text-heuristics";
import {
  buildResumeFromLines,
  line,
  positionedLine,
  requiredSection,
} from "./helpers/pdf-import-fixtures";
it("unrecognized header and section content", () => {
  const resume = buildResumeFromLines(
    [
      line("No Contact User", 0, 24),
      line("Senior Backend Engineer | 8 years of experience", 1, 14),
      line("Built resilient services for global teams.", 2),
      line("Delivered reliable tools with measurable results.", 3),
      line("Education", 4, 14),
      line("Example University", 5),
      line("2020 - 2024", 6),
    ],
    "Other",
  );
  assert.match(
    JSON.stringify(resume.basic),
    /Senior Backend Engineer/,
    "Headers without recognized contacts must retain the professional headline.",
  );
  assert.match(
    JSON.stringify(resume.basic),
    /Built resilient services/,
    "Headers without recognized contacts must retain the introduction.",
  );
  assert.match(JSON.stringify(resume.basic), /Delivered reliable tools/);

  const adjacentHeadings = buildResumeFromLines(
    [
      line("Test User", 0),
      line("test@example.com", 1),
      line("A heading with no body", 2, 16),
      line("Education", 3, 14),
      line("Experience", 4, 14),
      line("Example Company", 5),
      line("2020 - 2024", 6),
      line("Built reliable services.", 7),
    ],
    "Other",
  );
  assert.match(
    JSON.stringify(adjacentHeadings),
    /Education/,
    "An empty inferred section must preserve its source heading for review.",
  );
  assert.match(JSON.stringify(adjacentHeadings), /A heading with no body/);
  const combinedContacts = buildResumeFromLines(
    [
      line("Test User", 0),
      line("person@example.com +1 555 123 4567", 1),
      line("Wechat: portfolio-owner", 2),
      line("https://portfolio.example.com", 3),
      line("Education", 4),
      line("Example University", 5),
    ],
    "Other",
  );
  const combinedText = JSON.stringify(combinedContacts);
  assert.equal(
    combinedText.match(/person@example.com/g)?.length,
    1,
    "Preserving unclassified header content must not duplicate recognized contacts.",
  );
  assert.match(
    combinedText,
    /portfolio-owner/,
    "Text between separate contact rows must remain visible.",
  );
});

it("compact two column reading order", () => {
  const resume = buildResumeFromLines(
    [
      // Compact templates place profile details in a narrow left column and
      // the resume body in a wider right column. Interleaving these by y would
      // make the first right-column heading terminate the profile block.
      positionedLine("测试用户", 800, 40, 16),
      positionedLine("前端工程师", 780, 40),
      positionedLine("user@example.com", 760, 40),
      positionedLine("+86 138 0000 0000", 740, 40),
      positionedLine("关注复杂交互与稳定交付。", 720, 40),
      positionedLine("教育经历", 800, 340, 14),
      positionedLine("示例学院", 780, 340),
      positionedLine("2021.09 - 2025.06", 780, 540),
      positionedLine("软件工程", 760, 340),
      positionedLine("• 完成核心课程学习。", 720, 340),
      positionedLine("项目经历", 700, 340, 14),
      positionedLine("示例项目", 680, 340),
      positionedLine("项目负责人", 660, 340),
      positionedLine("2024.01 - 2024.12", 660, 540),
      positionedLine("• 完成项目交付。", 640, 340),
      positionedLine("• 提升使用效率。", 620, 340),
    ],
    "导入内容",
  );

  assert.equal(resume.basic.name, "测试用户");
  assert.equal(resume.basic.headline, "前端工程师");
  assert.equal(resume.basic.email, "user@example.com");
  assert.equal(resume.basic.phone, "+86 138 0000 0000");
  assert.equal(resume.basic.summary, "关注复杂交互与稳定交付。");
  assert.equal(requiredSection(resume, "education").items.length, 1);
  assert.equal(requiredSection(resume, "project").items.length, 1);
});

it("mixed single and two column reading order", () => {
  const pageWidth = 612;
  const resume = buildResumeFromLines(
    [
      positionedLine("Test User", 800, 40, 16, pageWidth),
      positionedLine("test@example.com", 780, 40, 10, pageWidth),
      positionedLine("Education", 750, 40, 14, pageWidth),
      positionedLine("Example School", 730, 40, 10, pageWidth),
      positionedLine("2020 - 2024", 730, 500, 10, pageWidth),
      positionedLine("Software Engineering", 710, 40, 10, pageWidth),
      positionedLine("Work Experience", 670, 40, 14, pageWidth),
      positionedLine("Example Organization", 650, 40, 10, pageWidth),
      positionedLine("2024 - Present", 630, 40, 10, pageWidth),
      positionedLine("Example Role", 610, 40, 10, pageWidth),
      positionedLine("• Improved a workflow.", 590, 40, 10, pageWidth),
      positionedLine("Skills", 670, 340, 14, pageWidth),
      positionedLine("TypeScript", 650, 340, 10, pageWidth),
      positionedLine("React", 630, 340, 10, pageWidth),
      positionedLine("Node.js", 610, 340, 10, pageWidth),
      positionedLine("Testing", 590, 340, 10, pageWidth),
      positionedLine("Accessibility", 570, 340, 10, pageWidth),
      positionedLine("Performance", 550, 340, 10, pageWidth),
      positionedLine("Databases", 530, 340, 10, pageWidth),
    ],
    "Imported content",
  );

  assert.equal(
    requiredSection(resume, "education").items[0]?.period,
    "2020 - 2024",
    "a right-aligned date in the single-column header must not move into a later column",
  );
});

it("disjoint two column reading order", () => {
  const pageWidth = 612;
  const leftColumn = 40;
  const rightColumn = 340;
  const lines = [
    positionedLine("Test User", 1000, leftColumn, 16, pageWidth),
    positionedLine("test@example.com", 980, leftColumn, 10, pageWidth),
    positionedLine("Work Experience", 920, leftColumn, 14, pageWidth),
    positionedLine("Example Organization", 900, leftColumn, 10, pageWidth),
    positionedLine("Example Role", 880, leftColumn, 10, pageWidth),
    positionedLine("2022 - Present", 860, leftColumn, 10, pageWidth),
    positionedLine("• Improved a workflow.", 840, leftColumn, 10, pageWidth),
    positionedLine(
      "• Reduced processing time.",
      820,
      leftColumn,
      10,
      pageWidth,
    ),
    positionedLine("• Documented the result.", 800, leftColumn, 10, pageWidth),
    positionedLine("Skills", 920, rightColumn, 14, pageWidth),
    ...[
      "TypeScript",
      "React",
      "Node.js",
      "Testing",
      "Accessibility",
      "SQL",
      "Git",
    ].map((text, index) =>
      positionedLine(text, 900 - index * 20, rightColumn, 10, pageWidth),
    ),
    positionedLine("Awards", 700, leftColumn, 14, pageWidth),
    positionedLine("Example Award", 680, leftColumn, 10, pageWidth),
    positionedLine("2023", 660, leftColumn, 10, pageWidth),
    positionedLine(
      "Recognized for reliable delivery.",
      640,
      leftColumn,
      10,
      pageWidth,
    ),
    positionedLine("Projects", 540, leftColumn, 14, pageWidth),
    positionedLine("Resume Workspace", 520, leftColumn, 10, pageWidth),
    positionedLine("Project Lead", 500, leftColumn, 10, pageWidth),
    positionedLine("2024 - Present", 480, leftColumn, 10, pageWidth),
    positionedLine(
      "• Built structured editing.",
      460,
      leftColumn,
      10,
      pageWidth,
    ),
    positionedLine(
      "• Added deterministic import.",
      440,
      leftColumn,
      10,
      pageWidth,
    ),
    positionedLine(
      "• Verified export quality.",
      420,
      leftColumn,
      10,
      pageWidth,
    ),
    positionedLine("Languages", 540, rightColumn, 14, pageWidth),
    ...[
      "English",
      "Mandarin",
      "Spanish",
      "French",
      "German",
      "Japanese",
      "Korean",
    ].map((text, index) =>
      positionedLine(text, 520 - index * 20, rightColumn, 10, pageWidth),
    ),
  ];
  const resume = buildResumeFromLines(lines, "Imported content");

  assert.deepEqual(
    resume.sections.map((section) => section.kind),
    ["experience", "simple_list", "achievement", "project", "simple_list"],
    "full-width content between independent column bands must keep its position",
  );
});

it("contact location extraction", () => {
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
});

it("project item grouping", () => {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("项目经历", 2, 14),
      line("React + TypeScript + Tailwind", 3),
      line("Reseno", 4),
      line("2026.03 - 至今", 5),
      line("AI Agent 简历制作网站", 6),
      line(
        "• 实现实时编辑、A4 预览、可折叠 section、关键词匹配与 PDF 导出。",
        7,
      ),
      line("• 将编辑器与真实简历版式拆分为结构化数据模型，渲染更加稳定。", 8),
    ],
    "导入内容",
  );
  const project = resume.sections.find((section) => section.kind === "project");

  assert.equal(project?.items.length, 1);
  assert.equal(project?.items[0]?.name, "Reseno");
  assert.equal(project?.items[0]?.period, "2026.03 - 至今");
  assert.equal(project?.items[0]?.highlights.length, 2);
});

it("publication item grouping", () => {
  const resume = buildResumeFromLines(
    [
      positionedLine("Ruoan Shen", 800),
      positionedLine("ruoan@example.com", 780),
      positionedLine("Selected Publications", 750, 40, 14),
      positionedLine("How Traceable Feedback Shapes Trust", 720),
      positionedLine("2026", 720, 500),
      positionedLine("Ruoan Shen, Maya Li", 700),
      positionedLine("National HCI Conference", 680),
      positionedLine("Poster accepted.", 660),
      positionedLine("When Explanations Improve Revision Decisions", 630),
      positionedLine("2025", 630, 500),
      positionedLine("Ruoan Shen, Daniel Wu", 610),
      positionedLine("Human-Centered AI Workshop", 590),
      positionedLine("Peer-reviewed workshop paper.", 570),
    ],
    "Imported content",
  );
  const publications = requiredSection(resume, "publication");

  assert.equal(publications.items.length, 2);
  assert.deepEqual(
    publications.items.map((item) => ({
      title: item.title,
      authors: item.authors,
      venue: item.venue,
      date: item.date,
    })),
    [
      {
        title: "How Traceable Feedback Shapes Trust",
        authors: "Ruoan Shen, Maya Li",
        venue: "National HCI Conference",
        date: "2026",
      },
      {
        title: "When Explanations Improve Revision Decisions",
        authors: "Ruoan Shen, Daniel Wu",
        venue: "Human-Centered AI Workshop",
        date: "2025",
      },
    ],
    "Publication import must preserve separate citation fields and item boundaries.",
  );
});

it("fallback section shape", () => {
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

  assert.equal(fallback?.kind, "simple_list");
  assert.equal(fallback?.title, "一段未识别标题");
  assert.equal(fallback?.items.length, 1);
  assert.ok(fallback?.kind === "simple_list");
  assert.equal(
    fallback?.items[0]?.content,
    "<ul><li>可以被保留的导入内容</li></ul>",
  );
});

it("inline section heading", () => {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("技能：能力一、能力二、能力三", 2),
    ],
    "导入内容",
  );
  const skills = requiredSection(resume, "skills");

  assert.equal(skills.items.length, 1);
  assert.equal(
    skills.items[0].content,
    "<ul><li>能力一、能力二、能力三</li></ul>",
  );
});

it("wrapped labeled list continuation", () => {
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line("user@example.com", 1),
      line("技能", 2, 14),
      line("工程能力：TypeScript、React、Node.js 与复杂状态管理", 3),
      line("及自动化测试", 4),
    ],
    "导入内容",
  );
  const skills = requiredSection(resume, "skills");

  assert.equal(skills.items.length, 1);
  assert.equal(
    skills.items[0].content,
    "<ul><li>工程能力：TypeScript、React、Node.js 与复杂状态管理及自动化测试</li></ul>",
  );
});

it("short bullets and continuation", () => {
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
  const work = requiredSection(resume, "work");

  assert.equal(work.items.length, 1);
  assert.equal(work.items[0]?.company, "示例公司");
  assert.equal(work.items[0]?.position, "示例岗位");
  assert.deepEqual(work.items[0]?.highlights, [
    "负责体验优化覆盖核心使用流程",
    "维护编辑器稳定性",
  ]);
});

it("adjacent experience items", () => {
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
  const work = requiredSection(resume, "work");

  assert.equal(work.items.length, 2);
  assert.equal(work.items[0]?.company, "第一公司");
  assert.equal(work.items[1]?.company, "第二公司");
  assert.equal(work.items[1]?.period, "2024.01 - 至今");
});

it("large experience title is not a section", () => {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line("test@example.com", 1),
      line("Work Experience", 2, 14),
      line("First Company", 3, 10),
      line("2022 - 2023", 4, 10),
      line("• Delivered the first result.", 5, 10),
      line("Second Company", 6, 13),
      line("2023 - 2024", 7, 10),
      line("• Delivered the second result.", 8, 10),
    ],
    "Imported content",
  );

  assert.deepEqual(
    requiredSection(resume, "work").items.map((item) => item.company),
    ["First Company", "Second Company"],
    "a prominent item title followed by a date remains inside its experience section",
  );
});

it("other section allows later inline experience", () => {
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line("user@example.com", 1),
      line("其他", 2, 14),
      line("技能：能力甲、能力乙", 3),
      line("工作经历：示例公司", 4),
      line("2024.01 - 2024.12", 5),
      line("示例岗位", 6),
      line("完成示例事项。", 7),
    ],
    "导入内容",
  );
  const other = requiredSection(resume, "other");
  const work = requiredSection(resume, "work");

  assert.equal(other.items.length, 1);
  assert.equal(
    other.items[0].content,
    "<ul><li>技能：能力甲、能力乙</li></ul>",
  );
  assert.equal(work.items[0]?.company, "示例公司");
});

it("multiline column metadata", () => {
  const resume = buildResumeFromLines(
    [
      positionedLine("测试用户", 800),
      positionedLine("user@example.com", 780),
      positionedLine("工作经历", 760, 40, 14),
      positionedLine("组织甲", 740, 40),
      positionedLine("元数据甲", 740, 360),
      positionedLine("岗位甲", 720, 40),
      positionedLine("元数据乙", 720, 360),
      positionedLine("2024.01 - 2024.12", 700, 360),
      positionedLine("完成示例事项。", 680, 40),
    ],
    "导入内容",
  );
  const work = requiredSection(resume, "work");

  assert.equal(work.items[0]?.company, "组织甲");
  assert.equal(work.items[0]?.position, "岗位甲");
  assert.equal(work.items[0]?.location, "元数据甲 · 元数据乙");
});

it("short unmarked body splits adjacent experiences", () => {
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line("user@example.com", 1),
      line("工作经历", 2, 14),
      line("组织甲", 3),
      line("2023.01 - 2023.12", 4),
      line("岗位甲", 5),
      line("完成甲项", 6),
      line("组织乙", 7),
      line("2024.01 - 2024.12", 8),
      line("岗位乙", 9),
      line("完成乙项", 10),
    ],
    "导入内容",
  );
  const work = requiredSection(resume, "work");

  assert.equal(work.items.length, 2);
  assert.deepEqual(
    work.items.map(({ company, period }) => ({ company, period })),
    [
      { company: "组织甲", period: "2023.01 - 2023.12" },
      { company: "组织乙", period: "2024.01 - 2024.12" },
    ],
  );
  assert.match(JSON.stringify(work.items[0]), /完成甲项/);
  assert.match(JSON.stringify(work.items[1]), /完成乙项/);
});

it("dotted technology headline", () => {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line("Senior Node.js Engineer", 1),
      line("user@example.com", 2),
      line("工作经历", 3, 14),
      line("示例组织", 4),
    ],
    "Imported content",
  );

  assert.equal(resume.basic.name, "Test User");
  assert.equal(resume.basic.headline, "Senior Node.js Engineer");
});

it("lexicon driven document title and period", () => {
  const resume = buildResumeFromLines(
    [
      line("Curriculum Vitae", 0),
      line("Test User", 1),
      line("user@example.com", 2),
      line("Work Experience", 3, 14),
      line("Example Organization", 4),
      line("2024.01 - Present", 5),
      line("Software Engineer", 6),
      line("• Improved a representative workflow.", 7),
    ],
    "Imported content",
  );
  const work = requiredSection(resume, "work");

  assert.equal(resume.basic.name, "Test User");
  assert.equal(work.items[0]?.period, "2024.01 - Present");
});

it("synthetic lexicon controls parsing", () => {
  // Regex metacharacters make this a stronger contract test: parsing must use
  // escaped backend terms rather than a hidden copy of the production words.
  const syntheticLexicon = {
    locales: {
      test: {
        documentTitleTerms: ["Career Sheet"],
        currentPeriodTerms: ["ongoing+"],
        dateRangeTerms: ["through+"],
        datePartSeparators: ["~"],
        datePartSuffixes: ["!"],
      },
    },
  };
  const resume = buildResumeFromLines(
    [
      line("ＣＡＲＥＥＲ   ＳＨＥＥＴ", 0),
      line("Test User", 1),
      line("user@example.com", 2),
      line("Work Experience", 3, 14),
      line("Example Organization", 4),
      line("2024~01! through+ ongoing+", 5),
      line("Software Engineer", 6),
      line("• Improved a representative workflow.", 7),
    ],
    "Imported content",
    syntheticLexicon,
  );
  const work = requiredSection(resume, "work");

  assert.equal(resume.basic.name, "Test User");
  assert.equal(work.items[0]?.period, "2024~01! through+ ongoing+");
});

it("localized date suffix parsing", () => {
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line("user@example.com", 1),
      line("工作经历", 2, 14),
      line("示例组织", 3),
      line("2024年01月 - 至今", 4),
      line("示例角色", 5),
    ],
    "导入内容",
  );

  assert.equal(
    requiredSection(resume, "work").items[0]?.period,
    "2024年01月 - 至今",
  );
});

it("imported content is not silently truncated", () => {
  const contactFields = Array.from(
    { length: 8 },
    (_, index) => `Site${index + 1}: profile${index + 1}.example`,
  ).join(" | ");
  const highlights = Array.from({ length: 8 }, (_, index) =>
    line(`• 完成第 ${index + 1} 项可验证成果。`, index + 6),
  );
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line(contactFields, 1),
      line("user@example.com", 2),
      line("工作经历", 3, 14),
      line("示例组织", 4),
      line("2024.01 - 2025.01", 5),
      ...highlights,
    ],
    "导入内容",
  );

  assert.equal(resume.basic.customFields.length, 8);
  assert.equal(requiredSection(resume, "work").items[0]?.highlights.length, 8);
});

it("unicode length limits use graphemes", () => {
  // Each character is one grapheme but two UTF-16 code units. The legacy
  // string.length check incorrectly rejected this valid 20-character name.
  const name = "𠮷".repeat(20);
  const resume = buildResumeFromLines(
    [
      line(name, 0),
      line("user@example.com", 1),
      line("教育经历", 2, 14),
      line("示例学院", 3),
    ],
    "导入内容",
  );

  assert.equal(resume.basic.name, name);
  assert.equal(countTextGraphemes("👩‍💻e\u0301"), 2);
  assert.equal(countTextGraphemes("禰\u{E0100}"), 1);
});

it("period year range", () => {
  const supported = buildResumeFromLines(
    [
      line("Test User", 0),
      line("user@example.com", 1),
      line("Work Experience", 2, 14),
      line("Example Organization", 3),
      line("2099.01 - 2100.01", 4),
      line("Example Role", 5),
    ],
    "Imported content",
  );
  assert.equal(
    requiredSection(supported, "work").items[0]?.period,
    "2099.01 - 2100.01",
  );

  const unsupported = buildResumeFromLines(
    [
      line("Test User", 0),
      line("user@example.com", 1),
      line("Work Experience", 2, 14),
      line("Example Organization", 3),
      line("2201.01 - 2202.01", 4),
      line("Example Role", 5),
    ],
    "Imported content",
  );
  assert.equal(requiredSection(unsupported, "work").items[0]?.period, "");

  const validAfterInvalidCandidate = buildResumeFromLines(
    [
      line("Test User", 0),
      line("user@example.com", 1),
      line("Work Experience", 2, 14),
      line("Reference 2201.01 - 2202.01", 3),
      line("Example Organization", 4),
      line("2021.01 - 2022.01", 5),
      line("Example Role", 6),
    ],
    "Imported content",
  );
  assert.equal(
    requiredSection(validAfterInvalidCandidate, "work").items[0]?.period,
    "2021.01 - 2022.01",
  );
});

it("section at document start does not become basic info", () => {
  const resume = buildResumeFromLines(
    [
      line("Work Experience", 0, 14),
      line("Example Organization", 1),
      line("2024.01 - 2025.01", 2),
      line("Example Role", 3),
      line("• Delivered a measurable result.", 4),
    ],
    "Imported content",
  );

  assert.equal(resume.basic.name, "");
  assert.equal(resume.basic.summary, "");
  assert.equal(requiredSection(resume, "work").items.length, 1);
});

it("strict period shapes", () => {
  const parsePeriod = (candidate: string) => {
    const resume = buildResumeFromLines(
      [
        line("Test User", 0),
        line("user@example.com", 1),
        line("Work Experience", 2, 14),
        line("Example Organization", 3),
        line(candidate, 4),
        line("Example Role", 5),
      ],
      "Imported content",
    );
    return requiredSection(resume, "work").items[0]?.period ?? "";
  };

  assert.equal(parsePeriod("2024.1 - 2025.12"), "2024.1 - 2025.12");
  assert.equal(parsePeriod("202401 - 202512"), "202401 - 202512");
  for (const invalid of [
    "2024.99 - 2025.42",
    "ISO2024-2025Plan",
    "2024--2025",
    "2024. - 2025",
    "2024 - Currently",
  ]) {
    assert.equal(parsePeriod(invalid), "", invalid);
  }
});

it("indented single column reading order", () => {
  const pageWidth = 612;
  const resume = buildResumeFromLines(
    [
      positionedLine("Skills", 800, 40, 14, pageWidth),
      positionedLine("Left 1", 780, 40, 10, pageWidth),
      positionedLine("Indented 1", 770, 130, 10, pageWidth),
      positionedLine("Indented 2", 760, 130, 10, pageWidth),
      positionedLine("Left 2", 750, 40, 10, pageWidth),
      positionedLine("Indented 3", 740, 130, 10, pageWidth),
      positionedLine("Side note", 735, 500, 10, pageWidth),
      positionedLine("Indented 4", 730, 130, 10, pageWidth),
      positionedLine("Left 3", 720, 40, 10, pageWidth),
      positionedLine("Indented 5", 710, 130, 10, pageWidth),
      positionedLine("Indented 6", 700, 130, 10, pageWidth),
      positionedLine("Left 4", 690, 40, 10, pageWidth),
      positionedLine("Indented 7", 680, 130, 10, pageWidth),
      positionedLine("Indented 8", 670, 130, 10, pageWidth),
    ],
    "Imported content",
  );
  const section = requiredSection(resume, "skills");
  assert.equal(section.items.length, 1);
  const titles = Array.from(
    section.items[0].content.matchAll(/<li>(.*?)<\/li>/g),
    (match) => match[1],
  );

  assert.deepEqual(titles.slice(0, 4), [
    "Left 1",
    "Indented 1",
    "Indented 2",
    "Left 2",
  ]);
});

it("contact parsing preserves location and urls", () => {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line(
        "user@example.com | San Francisco, CA | https://portfolio.example",
        1,
      ),
      line("Education", 2, 14),
      line("Example School", 3),
    ],
    "Imported content",
  );

  assert.equal(resume.basic.email, "user@example.com");
  assert.equal(resume.basic.location, "San Francisco, CA");
  assert.deepEqual(
    resume.basic.customFields.map(({ type, label, value }) => ({
      type,
      label,
      value,
    })),
    [
      {
        type: "url",
        label: "portfolio.example",
        value: "https://portfolio.example",
      },
    ],
    "an unlabeled web contact should remain available after import",
  );
});

it("date range is not a contact phone", () => {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line("2020 - 2024", 1),
      line("Education", 2, 14),
      line("Example School", 3),
    ],
    "Imported content",
  );

  assert.equal(
    resume.basic.phone,
    "",
    "a standalone employment or education date range is not a phone number",
  );
});

it("compact date range is not a contact phone", () => {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line("202001 - 202406", 1),
      line("Education", 2, 14),
      line("Example School", 3),
    ],
    "Imported content",
  );

  assert.equal(
    resume.basic.phone,
    "",
    "a compact year-month range is not a phone number",
  );
});

it("fullwidth contact and period", () => {
  const resume = buildResumeFromLines(
    [
      line("Ｔｅｓｔ Ｕｓｅｒ", 0),
      line("ｕｓｅｒ＠ｅｘａｍｐｌｅ．ｃｏｍ", 1),
      line("Work Experience", 2, 14),
      line("Example Organization", 3),
      line("２０２４．０１ - ２０２５．０６", 4),
      line("Example Role", 5),
    ],
    "Imported content",
  );

  assert.equal(resume.basic.name, "Test User");
  assert.equal(resume.basic.email, "user@example.com");
  assert.equal(
    requiredSection(resume, "work").items[0]?.period,
    "2024.01 - 2025.06",
  );
});
