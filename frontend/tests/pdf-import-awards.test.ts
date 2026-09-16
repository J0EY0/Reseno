import assert from "node:assert/strict";
import { it } from "vitest";
import { textContentToLinesForResumeImport } from "@/lib/pdf-resume-import/pdf-text-extraction";
import {
  buildResumeFromLines,
  requiredSection,
  positionedLine,
  textItem,
} from "./helpers/pdf-import-fixtures";

const awardTitles = [
  "2023年、2024年示例大学研究生学业一等奖学金",
  "示例工业大学研究与创新奖（团体）一等奖学金",
  "示例工业大学工匠之星二等奖学金、三等奖学金",
  "2022全国大学生建模竞赛全国一等奖",
  "2023全国大学生程序设计大赛一等奖",
  "计算机软件能力认证",
];

function compactAwardColumns() {
  return textContentToLinesForResumeImport(
    {
      items: [
        textItem("示例同学", 50, 780, { height: 18 }),
        textItem("荣誉奖励", 50, 120, { height: 12 }),
        ...awardTitles.map((title, index) =>
          textItem(title, index < 3 ? 50 : 310, 90 - (index % 3) * 16),
        ),
      ],
    },
    1,
    595,
  );
}

it("keeps both columns of a compact award block as independent text lines", () => {
  const lines = compactAwardColumns().filter((line) => line.y <= 90);
  assert.deepEqual(
    lines.map((line) => line.text).sort(),
    [...awardTitles].sort(),
  );
});

it("does not treat repeated ordinary word spaces as local column boundaries", () => {
  const lines = textContentToLinesForResumeImport(
    {
      items: Array.from({ length: 3 }, (_, index) => [
        textItem(
          "A paragraph continues across the page",
          50,
          700 - index * 16,
          { width: 256 },
        ),
        textItem("with the remaining sentence.", 310, 700 - index * 16, {
          width: 200,
        }),
      ]).flat(),
    },
    1,
    595,
  );
  assert.equal(lines.length, 3);
  assert.ok(
    lines.every(
      (line) =>
        line.text ===
        "A paragraph continues across the page with the remaining sentence.",
    ),
  );
});

it("imports every compact award cell as its own achievement", () => {
  const resume = buildResumeFromLines(compactAwardColumns(), "导入内容");
  const awards = requiredSection(resume, "awards");
  assert.equal(awards.items.length, 6);
  assert.deepEqual(
    awards.items.map((item) => item.name).sort(),
    [...awardTitles].sort(),
  );
});

it("keeps award dates and descriptions attached while separating adjacent titles", () => {
  const resume = buildResumeFromLines(
    [
      positionedLine("Example Candidate", 800, 50, 18),
      positionedLine("Awards", 760, 50, 14),
      positionedLine("Open Source Award | Example Foundation", 730, 50),
      positionedLine("2024", 730, 480),
      positionedLine("Recognized for accessible community tools.", 712, 62),
      positionedLine("Research Scholarship", 690, 50),
      positionedLine("2023", 672, 50),
      positionedLine("Supported research in distributed systems.", 654, 50),
      positionedLine("Student Leadership Award", 630, 50),
    ],
    "Imported content",
  );
  const awards = requiredSection(resume, "awards");
  assert.deepEqual(
    awards.items.map(({ name, issuer, date, description }) => ({
      name,
      issuer,
      date,
      description,
    })),
    [
      {
        name: "Open Source Award",
        issuer: "Example Foundation",
        date: "2024",
        description: "Recognized for accessible community tools.",
      },
      {
        name: "Research Scholarship",
        issuer: "",
        date: "2023",
        description: "Supported research in distributed systems.",
      },
      {
        name: "Student Leadership Award",
        issuer: "",
        date: "",
        description: "",
      },
    ],
  );
});

it("preserves a wrapped award title and explicit boundaries across languages", () => {
  const resume = buildResumeFromLines(
    [
      positionedLine("Example Candidate", 800, 50, 18),
      positionedLine("Awards", 760, 50, 14),
      positionedLine("• Outstanding Community", 730, 50),
      positionedLine("Contributions Award", 714, 62),
      positionedLine("• 國際學生研究獎", 690, 50),
      positionedLine("• Prix de l’innovation", 670, 50),
    ],
    "Imported content",
  );
  assert.deepEqual(
    requiredSection(resume, "awards").items.map((item) => item.name),
    [
      "Outstanding Community Contributions Award",
      "國際學生研究獎",
      "Prix de l’innovation",
    ],
  );
});

it("extracts inline date ranges and keeps right-column dates with their award", () => {
  const resume = buildResumeFromLines(
    [
      positionedLine("Example Candidate", 800, 50, 18),
      positionedLine("Awards", 760, 50, 14),
      positionedLine(
        "Research Fellowship | Example Foundation | 2022 - 2024",
        730,
        50,
      ),
      positionedLine("Academic Distinction", 706, 50),
      positionedLine("2021", 706, 480),
      positionedLine("Community Recognition", 682, 50),
      positionedLine("2020", 682, 480),
    ],
    "Imported content",
  );
  assert.deepEqual(
    requiredSection(resume, "awards").items.map(({ name, issuer, date }) => ({
      name,
      issuer,
      date,
    })),
    [
      {
        name: "Research Fellowship",
        issuer: "Example Foundation",
        date: "2022 - 2024",
      },
      { name: "Academic Distinction", issuer: "", date: "2021" },
      { name: "Community Recognition", issuer: "", date: "2020" },
    ],
  );
});

it("keeps sentence punctuation from merging standalone awards", () => {
  const resume = buildResumeFromLines(
    [
      positionedLine("Example Candidate", 800, 50, 18),
      positionedLine("Awards", 760, 50, 14),
      positionedLine("Research Excellence.", 730, 50),
      positionedLine("Community Leadership.", 710, 50),
      positionedLine("Academic Distinction.", 690, 50),
    ],
    "Imported content",
  );
  assert.deepEqual(
    requiredSection(resume, "awards").items.map((item) => item.name),
    ["Research Excellence.", "Community Leadership.", "Academic Distinction."],
  );
});
