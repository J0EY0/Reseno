import assert from "node:assert/strict";
import { it } from "vitest";
import { createResumeImportLexiconContext } from "@/lib/pdf-resume-import/parser-config";
import { buildSectionItems } from "@/lib/pdf-resume-import/section-items";
import {
  buildResumeFromLines,
  positionedLine,
  requiredSection,
  resumeImportLexicon,
} from "./helpers/pdf-import-fixtures";

const lexicon = createResumeImportLexiconContext(resumeImportLexicon);

it("splits education headers with inline dates before classifying their text", () => {
  const items = buildSectionItems(
    [
      positionedLine(
        "示例理工大学（2022.09 - 2025.06）｜计算机技术 硕士｜GPA: 3.90 / 4.0（Rank: 2 / 60）",
        760,
      ),
      positionedLine("研究方向：分布式系统 / 软件工程 / 数据分析", 740, 62),
      positionedLine(
        "示例工程大学（2020.09 - 2022.06）｜软件工程 学士｜GPA: 3.70 / 4.0（Rank: 8 / 120）",
        710,
      ),
      positionedLine("主修课程：软件工程与数据结构", 690),
    ],
    "education",
    lexicon,
  );

  assert.equal(items.length, 2);
  assert.equal(items[0]?.title, "示例理工大学");
  assert.equal(items[1]?.title, "示例工程大学");
  assert.equal(items[0]?.subtitle, "计算机技术 硕士");
  assert.equal(items[0]?.meta, "GPA: 3.90 / 4.0（Rank: 2 / 60）");
  assert.equal(items[0]?.period, "2022.09 - 2025.06");
  assert.equal(items[1]?.period, "2020.09 - 2022.06");
  assert.match(JSON.stringify(items[0]), /研究方向/);
  assert.doesNotMatch(JSON.stringify(items[1]), /研究方向/);
});

it("splits undated project headers from indented descriptions", () => {
  const items = buildSectionItems(
    [
      positionedLine("文档协作平台", 760),
      positionedLine("项目简介：为团队提供文档编辑、审阅和协作能力。", 740, 52),
      positionedLine("项目职责：实现编辑与审阅流程。", 720, 52),
      positionedLine("数据分析工具", 690),
      positionedLine("项目简介：帮助用户检查数据与生成图表。", 670, 52),
    ],
    "project",
    lexicon,
  );

  assert.deepEqual(
    items.map((item) => item.title),
    ["文档协作平台", "数据分析工具"],
  );
  assert.doesNotMatch(JSON.stringify(items[0]), /数据分析工具/);
  assert.match(JSON.stringify(items[1]), /生成图表/);
});

it("splits undated English projects using title typography", () => {
  const items = buildSectionItems(
    [
      positionedLine("Document Workspace", 760, 40, 12),
      positionedLine("Built accessible editing and review workflows.", 740),
      positionedLine("Improved collaboration across distributed teams.", 720),
      positionedLine("Data Explorer", 690, 40, 12),
      positionedLine("Delivered interactive data visualization tools.", 670),
    ],
    "project",
    lexicon,
  );

  assert.deepEqual(
    items.map((item) => item.title),
    ["Document Workspace", "Data Explorer"],
  );
  assert.doesNotMatch(JSON.stringify(items[0]), /Data Explorer/);
});

it("preserves long international institution names in inline education headers", () => {
  const items = buildSectionItems(
    [
      positionedLine(
        "International Institute of Science and Technology (2022 - 2024) | MSc Computer Science | GPA: 3.9 / 4.0",
        760,
      ),
      positionedLine("Research in distributed systems.", 740, 52),
      positionedLine(
        "École supérieure des sciences appliquées (2018 - 2022) | BSc Computing | GPA: 3.8 / 4.0",
        710,
      ),
    ],
    "education",
    lexicon,
  );

  assert.deepEqual(
    items.map((item) => item.title),
    [
      "International Institute of Science and Technology",
      "École supérieure des sciences appliquées",
    ],
  );
  assert.equal(items[0]?.subtitle, "MSc Computer Science");
  assert.match(items[0]?.description ?? "", /distributed systems/);
});

it("keeps each undated project with its same-row metadata and wrapped body", () => {
  const items = buildSectionItems(
    [
      positionedLine("\uf02e 文档协作平台", 760, 37),
      positionedLine("实验项目", 760, 360),
      positionedLine("项目说明：团队成员能够编辑", 740, 51),
      positionedLine("与审核协作文档。", 724, 51),
      positionedLine("\uf02e 数据分析工具", 704, 37),
      positionedLine("竞赛获奖作品", 704, 310),
      positionedLine("项目说明：生成数据图表。", 684, 51),
    ],
    "project",
    lexicon,
  );

  assert.deepEqual(
    items.map(({ title, meta }) => ({ title, meta })),
    [
      { title: "文档协作平台", meta: "" },
      { title: "数据分析工具", meta: "" },
    ],
  );
  assert.equal(
    items[0]?.description,
    "实验项目\n\n项目说明：团队成员能够编辑与审核协作文档。",
  );
  assert.match(items[1]?.description ?? "", /竞赛获奖作品/);
});

it("preserves project awards and funding as prose while recognizing technology lists", () => {
  const resume = buildResumeFromLines(
    [
      positionedLine("Projects", 800, 40, 14),
      positionedLine("Document Workspace", 780, 40),
      positionedLine("University research grant", 780, 360),
      positionedLine("Built accessible document editing.", 760, 52),
      positionedLine("Data Explorer", 730, 40),
      positionedLine("National competition award", 730, 360),
      positionedLine("Implemented an interactive data explorer.", 710, 52),
      positionedLine("Quality Dashboard", 680, 40),
      positionedLine("TypeScript + React + Tailwind", 680, 360),
      positionedLine("Delivered quality monitoring for the team.", 660, 52),
    ],
    "Imported content",
  );
  const projects = requiredSection(resume, "project").items;

  assert.equal(projects.length, 3);
  assert.deepEqual(projects[0]?.techStack, []);
  assert.match(projects[0]?.description ?? "", /University research grant/);
  assert.match(projects[0]?.description ?? "", /accessible document editing/);
  assert.deepEqual(projects[1]?.techStack, []);
  assert.match(projects[1]?.description ?? "", /National competition award/);
  assert.deepEqual(projects[2]?.techStack, ["TypeScript", "React", "Tailwind"]);
});
