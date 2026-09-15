// @vitest-environment node
import assert from "node:assert/strict";
import { it } from "vitest";

import presets from "../../backend/app/services/template_presets.json";
import type { AppMessages } from "@/i18n";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";
import {
  createTemplatePreviewResumes,
  getTemplatePreviewResume,
  TEMPLATE_PREVIEW_SCENARIOS,
} from "@/lib/template-preview-resume";

const expectedScenarios = [
  "earlyCareer",
  "experienced",
  "executive",
  "research",
];
const expectedLayouts = {
  minimal: ["split", "list", "right"],
  modern: ["stacked", "inline", "center"],
  compact: ["compact", "columns", "right"],
  classic: ["split", "list", "right"],
  executive: ["compact", "list", "right"],
  academic: ["split", "list", "none"],
};

it("declares the four product preview scenarios", () => {
  assert.deepEqual(
    TEMPLATE_PREVIEW_SCENARIOS,
    expectedScenarios,
    "Template previews must keep each product scenario explicit.",
  );
});
function assertValidPreviewSet(
  messages: AppMessages,
  locale: string,
  expectedSeparator: string,
) {
  const previews = createTemplatePreviewResumes(messages);
  const samples = messages.templatePreviewSamples;
  const expectedSections = {
    earlyCareer: [
      ["education", ""],
      ["experience", samples.earlyCareer.experienceSectionTitle],
      ["project", samples.earlyCareer.projectSectionTitle],
      ["achievement", samples.earlyCareer.achievementSectionTitle],
      ["simple_list", samples.earlyCareer.skillsSectionTitle],
    ],
    experienced: [
      ["experience", samples.experienced.experienceSectionTitle],
      ["project", samples.experienced.projectSectionTitle],
      ["achievement", samples.experienced.achievementSectionTitle],
      ["simple_list", samples.experienced.skillsSectionTitle],
      ["education", ""],
    ],
    executive: [
      ["experience", samples.executive.experienceSectionTitle],
      ["project", samples.executive.projectSectionTitle],
      ["achievement", samples.executive.achievementSectionTitle],
      ["simple_list", samples.executive.skillsSectionTitle],
      ["education", ""],
    ],
    research: [
      ["education", ""],
      ["experience", samples.research.researchSectionTitle],
      ["publication", samples.research.publicationSectionTitle],
      ["experience", samples.research.teachingSectionTitle],
      ["achievement", samples.research.achievementSectionTitle],
      ["simple_list", samples.research.skillsSectionTitle],
    ],
  };

  assert.deepEqual(
    Object.keys(previews),
    expectedScenarios,
    `${locale} must build exactly one fixture per product scenario.`,
  );

  for (const scenario of TEMPLATE_PREVIEW_SCENARIOS) {
    const resume = previews[scenario];
    assert.equal(
      resume.schemaVersion,
      2,
      `${locale}/${scenario} must use ResumeData V2.`,
    );
    assert.deepEqual(
      resume.sections.map((section) => [section.kind, section.title]),
      expectedSections[scenario],
      `${locale}/${scenario} must keep its exact section order and titles.`,
    );
    assert.equal(
      resume.basic.customFields.length,
      1,
      `${locale}/${scenario} must include one compact portfolio field.`,
    );

    const ids = [
      ...resume.basic.customFields.map((field) => field.id),
      ...resume.sections.flatMap((section) => [
        section.id,
        ...section.items.map((item) => item.id),
      ]),
    ];
    assert.equal(
      new Set(ids).size,
      ids.length,
      `${locale}/${scenario} fixture ids must be unique.`,
    );
    assert.ok(
      ids.every((id) => /^[a-z0-9-]+$/.test(id)),
      `${locale}/${scenario} fixture ids must remain contract-safe.`,
    );

    const skillSection = resume.sections.find(
      (section) => section.kind === "simple_list",
    );
    assert.ok(skillSection);
    assert.equal(skillSection.items.length, 1);
    assert.match(
      skillSection.items[0].content,
      /^<ul><li>.+<\/li><\/ul>$/,
      `${locale}/${scenario} skills must remain serialized rich text.`,
    );
    assert.match(
      skillSection.items[0].content,
      new RegExp(expectedSeparator),
      `${locale}/${scenario} skills must use locale-appropriate punctuation.`,
    );
  }

  assert.match(previews.earlyCareer.basic.avatar, /^data:image\/svg\+xml,/);
  assert.match(previews.experienced.basic.avatar, /^data:image\/svg\+xml,/);
  assert.match(previews.executive.basic.avatar, /^data:image\/svg\+xml,/);
  assert.equal(previews.research.basic.avatar, "");
  assert.equal(previews.earlyCareer.sections[1].items.length, 1);
  assert.equal(previews.experienced.sections[0].items.length, 2);
  assert.equal(previews.experienced.sections.at(-1)!.kind, "education");
  assert.equal(previews.executive.sections[0].items.length, 2);
  assert.equal(previews.executive.sections[2].items.length, 1);
  assert.equal(previews.research.sections[1].items.length, 1);
  assert.equal(previews.research.sections[2].items.length, 1);
  assert(previews.research.sections[2].kind === "publication");
  assert.ok(
    previews.research.sections[2].items.every(
      (item) => item.title && item.authors && item.venue && item.date,
    ),
    `${locale}/research publications must keep structured citation fields.`,
  );
  assert.equal(previews.research.sections[4].items.length, 1);

  for (const preset of Object.keys(presets) as Array<keyof typeof presets>) {
    const scenario = presets[preset].starter as keyof typeof previews;
    assert.equal(
      getTemplatePreviewResume(previews, { preset }),
      previews[scenario],
      `${locale}/${preset} must resolve the ${scenario} fixture by preset.`,
    );
  }
}

it.each([
  { messages: en, locale: "en", separator: ": " },
  { messages: zh, locale: "zh", separator: "：" },
])(
  "builds valid localized preview scenarios for $locale",
  ({ messages, locale, separator }) => {
    assertValidPreviewSet(messages, locale, separator);
  },
);

it("keeps all canonical preset layouts distinct", () => {
  assert.deepEqual(
    Object.keys(presets),
    Object.keys(expectedLayouts),
    "The preview contract must cover every canonical built-in preset.",
  );

  for (const [presetId, expected] of Object.entries(expectedLayouts) as Array<
    [keyof typeof expectedLayouts, string[]]
  >) {
    const layout = presets[presetId].layout;
    assert.deepEqual(
      [layout.timelineItemLayout, layout.listItemLayout, layout.avatarPosition],
      expected,
      `${presetId} must keep its differentiated content hierarchy.`,
    );
  }
});
