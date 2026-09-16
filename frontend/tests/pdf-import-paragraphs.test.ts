import assert from "node:assert/strict";
import { it } from "vitest";
import type { TextLine } from "@/lib/pdf-resume-import/pdf-text-extraction";
import { joinWrappedLines } from "@/lib/pdf-resume-import/text-heuristics";
import {
  buildResumeFromLines,
  positionedLine,
  requiredSection,
} from "./helpers/pdf-import-fixtures";

function row(text: string, y: number, width: number, x = 40): TextLine {
  return { ...positionedLine(text, y, x), width };
}

it("preserves CJK punctuation without adding spaces at a physical line break", () => {
  assert.equal(
    joinWrappedLines(["安排工作，", "并与团队协作"]),
    "安排工作，并与团队协作",
  );
  assert.equal(
    joinWrappedLines(["完成工作", "（包括验证）"]),
    "完成工作（包括验证）",
  );
  assert.equal(
    joinWrappedLines(["Reviewed results,", "then shared findings."]),
    "Reviewed results, then shared findings.",
  );
});

function listItems(lines: TextLine[]) {
  const resume = buildResumeFromLines(
    [positionedLine("Other", 800, 40, 14), ...lines],
    "Other",
  );
  const section = requiredSection(resume, "simple_list");
  const holder = document.createElement("div");
  holder.innerHTML = section.items[0].content;
  return Array.from(holder.querySelectorAll("li"), (item) => item.textContent);
}

it("joins full-width Chinese continuation lines into one list paragraph", () => {
  assert.deepEqual(
    listItems([
      row(
        "针对不同环境下的分布变化以及在线适应过程中的知识遗忘问题提出新的适应框架，利",
        760,
        400,
      ),
      row(
        "用历史向量表示模型更新方向，并通过动态融合机制持续适应新的数据分布，同时实",
        744,
        396,
      ),
      row("现在线更新和知识保留", 728, 290),
      row("在多个数据集上验证方法效果", 711, 280),
      row("负责算法设计与实验分析", 695, 220),
    ]),
    [
      "针对不同环境下的分布变化以及在线适应过程中的知识遗忘问题提出新的适应框架，利用历史向量表示模型更新方向，并通过动态融合机制持续适应新的数据分布，同时实现在线更新和知识保留",
      "在多个数据集上验证方法效果",
      "负责算法设计与实验分析",
    ],
  );
});

it("joins English wrapped prose while keeping separate short list entries", () => {
  assert.deepEqual(
    listItems([
      row("Designed a document processing system that supports", 760, 400),
      row("reliable extraction across several input formats.", 744, 300),
      row("Reviewed performance benchmarks", 724, 250),
      row("Presented results to the team", 708, 220),
    ]),
    [
      "Designed a document processing system that supports reliable extraction across several input formats.",
      "Reviewed performance benchmarks",
      "Presented results to the team",
    ],
  );
});

it("keeps sentences in one paragraph when a full-width line ends with punctuation", () => {
  assert.deepEqual(
    listItems([
      row(
        "Builds reliable services through design and quality checks.",
        760,
        400,
      ),
      row("Uses reproducible methods to investigate failures.", 744, 350),
      row("Communicates findings and records technical decisions.", 709, 400),
    ]),
    [
      "Builds reliable services through design and quality checks. Uses reproducible methods to investigate failures.",
      "Communicates findings and records technical decisions.",
    ],
  );
});

it("accounts for a long word moving to the next physical line", () => {
  assert.deepEqual(
    listItems([
      row(
        "Studied document structure using reproducible evaluation methods.",
        760,
        510,
      ),
      row("Recorded experimental conditions and identified useful", 744, 474),
      row("improvements and open questions for subsequent research.", 728, 340),
    ]),
    [
      "Studied document structure using reproducible evaluation methods. Recorded experimental conditions and identified useful improvements and open questions for subsequent research.",
    ],
  );
});

it("respects explicit bullets, paragraph gaps, and neighboring columns", () => {
  assert.deepEqual(
    listItems([
      row("• Designed reliable tools", 760, 390),
      row("• Delivered accessible interfaces", 744, 400),
      row("New paragraph after vertical spacing", 700, 400),
      row("Right column entry", 684, 200, 360),
    ]),
    [
      "Designed reliable tools",
      "Delivered accessible interfaces",
      "New paragraph after vertical spacing",
      "Right column entry",
    ],
  );
});

it("preserves separate list entries marked with private-use font glyphs", () => {
  const entries = [
    "Experienced with Python, TypeScript, and Java",
    "Familiar with Docker, Kubernetes, and Ansible",
    "Comfortable with SQL, Redis, and MongoDB",
  ];
  assert.deepEqual(
    listItems(
      entries.map((text, index) =>
        row(`\uf0b7 ${text}`, 760 - index * 20, 300),
      ),
    ),
    entries,
  );
});

it("keeps labeled entries and joins their measured continuation lines", () => {
  assert.deepEqual(
    listItems([
      row("Research: Reliable document processing and", 760, 400),
      row("layout reconstruction across languages", 744, 300),
      row("Languages: English, 中文", 728, 260),
    ]),
    [
      "Research：Reliable document processing and layout reconstruction across languages",
      "Languages：English, 中文",
    ],
  );
});
