// @vitest-environment node
import assert from "node:assert/strict";
import React, { type ReactNode } from "react";
import { renderToReadableStream } from "react-dom/server";
import { expect, it } from "vitest";

import { createResumeDiffLookup } from "@/components/preview/resume-preview-diff-lookup";
import {
  createInlineDiffParts,
  createListDiff,
} from "@/components/preview/resume-preview-diff-algorithms";
import { getRenderableFieldDiffs } from "@/components/preview/resume-preview-diffs";
import { ResumeDiffText } from "@/components/preview/resume-preview-diff-text";
import { getRenderableItems } from "@/components/preview/resume-preview-model";
import {
  RichHighlights,
  RichListDiff,
} from "@/components/preview/resume-preview-rich-diff";
import { SectionItems } from "@/components/preview/resume-preview-section-items";
import zh from "@/i18n/locales/zh.json";
import { projectResumeSection } from "@/lib/resume-sections";
import { createTemplateLayout, createTemplateSettings } from "@/lib/templates";
import type { ResumeDraftDiff } from "@/types/resume";

const layout = createTemplateLayout("minimal", { timelineItemLayout: "split" });
const settings = createTemplateSettings("minimal", {
  bodyColor: "#334155",
  bodyLineHeight: 1.6,
  bodyScale: 1,
  itemGap: 1,
  itemTitleScale: 1.1,
  metaScale: 0.9,
});
const messages = {
  ...zh,
  agentDiffAdded: "已新增",
  agentDiffDeleted: "已删除",
  agentDiffModified: "已修改",
  agentDiffMoved: "已移动",
};

async function renderMarkup(element: ReactNode) {
  const stream = await renderToReadableStream(element);
  await stream.allReady;
  return new Response(stream).text();
}

function experienceLookup() {
  return createResumeDiffLookup([
    {
      id: "diff-position-1",
      operationId: "edit-position-1",
      path: "sections.experience.items.tencent.position",
      kind: "modified",
      label: "修正职位",
      sectionId: "experience",
      itemId: "tencent",
      before: "腾讯",
      after: "前端开发实习生",
    },
    {
      id: "diff-description",
      operationId: "edit-description",
      path: "sections.experience.items.tencent.description",
      kind: "modified",
      label: "精简描述",
      sectionId: "experience",
      itemId: "tencent",
      before: "企业协同产品线，参与后台管理系统和内容编辑器的体验优化。",
      after: "参与后台管理系统与内容编辑器体验优化。",
    },
    {
      id: "diff-highlights",
      operationId: "edit-highlights",
      path: "sections.experience.items.tencent.highlights",
      kind: "modified",
      label: "收紧 bullet",
      sectionId: "experience",
      itemId: "tencent",
      before: ["第一条不变", "第二条旧文本"],
      after: ["第一条不变", "第二条新文本"],
    },
    {
      id: "diff-position-2",
      operationId: "edit-position-2",
      path: "sections.experience.items.tencent.position",
      kind: "modified",
      label: "再次修正职位",
      sectionId: "experience",
      itemId: "tencent",
      before: "前端开发实习生",
      after: "AI 前端开发实习生",
    },
  ]);
}

it("compacts sequential fields and clears reverted highlights", () => {
  const lookup = experienceLookup();
  const itemDiff = lookup.itemDiffById.get("tencent");

  assert(itemDiff, "The changed item must be addressable by item id.");
  expect(itemDiff.structuralDiff).toBe(undefined);
  expect([...itemDiff.fieldDiffByName.keys()]).toStrictEqual([
    "position",
    "description",
    "highlights",
  ]);
  expect(itemDiff.fieldDiffByName.get("position")).toStrictEqual({
    id: "diff-position-2",
    operationId: "edit-position-2",
    path: "sections.experience.items.tencent.position",
    kind: "modified",
    label: "再次修正职位",
    sectionId: "experience",
    itemId: "tencent",
    before: "腾讯",
    after: "AI 前端开发实习生",
  });

  const revertedLookup = createResumeDiffLookup([
    {
      id: "diff-summary-a-b",
      operationId: "edit-summary-a-b",
      path: "basic.summary",
      kind: "modified",
      label: "修改总结",
      before: "A",
      after: "B",
    },
    {
      id: "diff-summary-b-a",
      operationId: "edit-summary-b-a",
      path: "basic.summary",
      kind: "modified",
      label: "恢复总结",
      before: "B",
      after: "A",
    },
  ]);
  expect(revertedLookup.basicDiffByField.size).toBe(0);
  expect(getRenderableFieldDiffs(itemDiff, "experience", "title").length).toBe(
    0,
  );
  expect(
    getRenderableFieldDiffs(itemDiff, "experience", "subtitle").map(
      (diff) => diff.path,
    ),
  ).toStrictEqual(["sections.experience.items.tencent.position"]);
});

it("maps publication changes to their matching citation slots", () => {
  const publicationLookup = createResumeDiffLookup([
    {
      id: "diff-publication-title",
      operationId: "edit-publication-title",
      path: "sections.publications.items.paper-1.title",
      kind: "modified",
      label: "Update publication title",
      sectionId: "publications",
      itemId: "paper-1",
      before: "Old title",
      after: "New title",
    },
    {
      id: "diff-publication-authors",
      operationId: "edit-publication-authors",
      path: "sections.publications.items.paper-1.authors",
      kind: "modified",
      label: "Update authors",
      sectionId: "publications",
      itemId: "paper-1",
      before: "Ruoan Shen",
      after: "Ruoan Shen, Maya Li",
    },
    {
      id: "diff-publication-venue",
      operationId: "edit-publication-venue",
      path: "sections.publications.items.paper-1.venue",
      kind: "modified",
      label: "Update venue",
      sectionId: "publications",
      itemId: "paper-1",
      before: "Workshop",
      after: "National HCI Conference",
    },
  ]).itemDiffById.get("paper-1");
  expect({
    title: getRenderableFieldDiffs(
      publicationLookup,
      "publication",
      "title",
    ).map((diff) => diff.path),
    subtitle: getRenderableFieldDiffs(
      publicationLookup,
      "publication",
      "subtitle",
    ).map((diff) => diff.path),
    meta: getRenderableFieldDiffs(publicationLookup, "publication", "meta").map(
      (diff) => diff.path,
    ),
  }).toStrictEqual({
    title: ["sections.publications.items.paper-1.title"],
    subtitle: ["sections.publications.items.paper-1.authors"],
    meta: ["sections.publications.items.paper-1.venue"],
  });
});

it("marks only rewritten list entries and retains deletion state", () => {
  expect([
    ...createListDiff(
      ["第一条不变", "第二条旧文本"],
      ["第一条不变", "第二条新文本"],
    ).changedIndices,
  ]).toStrictEqual([1]);
  expect([
    ...createListDiff(["保留", "删除"], ["保留"]).changedIndices,
  ]).toStrictEqual([]);
  expect(createListDiff(["保留", "删除原文"], ["保留"]).hasDeletions).toBe(
    true,
  );
});

it("reproduces candidate inline text without marking unchanged or deleted words", () => {
  const inlineParts = createInlineDiffParts(
    "负责编辑器表单模块重构，页面状态管理复杂度显著下降。",
    "负责编辑器表单模块重构，显著降低页面状态管理复杂度。",
  );
  expect(inlineParts.map((part) => part.value).join("")).toBe(
    "负责编辑器表单模块重构，显著降低页面状态管理复杂度。",
  );
  assert(
    inlineParts.some((part) => part.changed) &&
      inlineParts.some((part) => !part.changed),
    "A rewrite must mark only changed words, not the entire field.",
  );
  const deletionOnlyInlineParts = createInlineDiffParts(
    "负责复杂的前端架构设计",
    "负责前端架构设计",
  );
  expect(deletionOnlyInlineParts.map((part) => part.value).join("")).toBe(
    "负责前端架构设计",
  );
  expect(deletionOnlyInlineParts.some((part) => part.changed)).toBe(false);
});

it.each([
  ["Engineer", "<p><strong>Engineer</strong></p>"],
  ["<p><strong>Engineer</strong></p>", "Engineer"],
])(
  "marks formatting from %s to %s without escaped tags",
  async (before, after) => {
    const formatRendered = await renderMarkup(
      React.createElement(ResumeDiffText, {
        richText: true,
        value: after,
        diffs: [
          {
            id: "format-position",
            operationId: "format-position",
            path: "sections.experience.items.tencent.position",
            kind: "modified",
            label: "Format position",
            before,
            after,
          },
        ],
      }),
    );
    expect(formatRendered).toMatch(/resume-diff-field--whole/);
    expect(formatRendered).toMatch(
      /data-resume-diff-path="sections\.experience\.items\.tencent\.position"/,
    );
    expect(formatRendered).not.toMatch(/&lt;(?:p|strong)&gt;/);
  },
);

it("retains the canonical review path when a scalar field is cleared", async () => {
  const clearedFieldRendered = await renderMarkup(
    React.createElement(ResumeDiffText, {
      value: "",
      diffs: [
        {
          id: "diff-clear-summary",
          operationId: "edit-clear-summary",
          path: "basic.summary",
          kind: "modified",
          label: "清空个人总结",
          before: "原个人总结",
          after: "",
        },
      ],
    }),
  );
  expect(clearedFieldRendered).toMatch(
    /data-resume-diff-path="basic\.summary"/,
  );
  expect(clearedFieldRendered).not.toMatch(
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|>−</,
  );
});

it("marks a deletion-only rewrite without overlaying live text", async () => {
  const deletionOnlyTextRendered = await renderMarkup(
    React.createElement(ResumeDiffText, {
      value: "负责前端架构设计",
      diffs: [
        {
          id: "diff-remove-words",
          operationId: "edit-remove-words",
          path: "sections.experience.items.tencent.description",
          kind: "modified",
          label: "精简描述",
          sectionId: "experience",
          itemId: "tencent",
          before: "负责复杂的前端架构设计",
          after: "负责前端架构设计",
        },
      ],
    }),
  );
  expect(deletionOnlyTextRendered).toMatch(/resume-diff-field--whole/);
  expect(deletionOnlyTextRendered).not.toMatch(
    /resume-diff-deletion-marker|resume-diff-inline-deletion|data-resume-diff-deletion-boundary|>−</,
  );
});

it("marks changed timeline slots and leaves the company and unchanged bullet plain", async () => {
  const lookup = experienceLookup();
  const rendered = await renderMarkup(
    React.createElement(SectionItems, {
      itemDiffById: lookup.itemDiffById,
      layout,
      section: {
        id: "experience",
        kind: "experience",
        layout: "timeline",
        title: "工作 / 实习经历",
        items: [
          {
            id: "tencent",
            title: "腾讯",
            subtitle: "AI 前端开发实习生",
            meta: "深圳",
            period: "2022.07 - 2022.09",
            description: "参与后台管理系统与内容编辑器体验优化。",
            highlights: ["第一条不变", "第二条新文本"],
            content: "",
            url: "",
          },
        ],
      },
      settings,
      t: messages,
      enableContactLinks: false,
    }),
  );
  expect(rendered).not.toMatch(/resume-diff--modified/);
  expect(rendered).toMatch(/data-resume-diff-label="已修改"/);
  expect(rendered).toMatch(/<h3[^>]*><span>腾讯<\/span><\/h3>/);
  expect(rendered).toMatch(
    /data-resume-diff-path="sections\.experience\.items\.tencent\.position"/,
  );
  expect(rendered).toMatch(
    /<li(?: class="")?><span>第一条不变<\/span><\/li><li class="resume-diff-field resume-diff-field--whole"[^>]*><span>第二条新文本<\/span><\/li>/,
  );
});

it("keeps the cleared subtitle review path in its empty slot", async () => {
  const clearedPositionLookup = createResumeDiffLookup([
    {
      id: "diff-clear-position",
      operationId: "edit-clear-position",
      path: "sections.experience.items.tencent.position",
      kind: "modified",
      label: "清空职位",
      sectionId: "experience",
      itemId: "tencent",
      before: "前端开发实习生",
      after: "",
    },
  ]);
  const clearedPositionRendered = await renderMarkup(
    React.createElement(SectionItems, {
      itemDiffById: clearedPositionLookup.itemDiffById,
      layout,
      section: {
        id: "experience",
        kind: "experience",
        layout: "timeline",
        title: "工作经历",
        items: [
          {
            id: "tencent",
            title: "腾讯",
            subtitle: "",
            meta: "",
            period: "",
            description: "",
            highlights: [],
            content: "",
            url: "",
          },
        ],
      },
      settings,
      t: messages,
      enableContactLinks: false,
    }),
  );
  expect(clearedPositionRendered).toMatch(
    /data-resume-diff-path="sections\.experience\.items\.tencent\.position"/,
  );
});

it("marks a changed degree separately from the unchanged major", async () => {
  const educationSection = projectResumeSection({
    id: "education",
    kind: "education",
    title: "教育经历",
    items: [
      {
        id: "zju",
        school: "浙江大学",
        degree: "工学学士",
        major: "计算机科学与技术",
        gpa: "3.85 / 4.0",
        location: "杭州",
        period: "2019.09 - 2023.06",
        description: "",
        highlights: [],
      },
    ],
  });
  const educationLookup = createResumeDiffLookup([
    {
      id: "diff-degree",
      operationId: "edit-degree",
      path: "sections.education.items.zju.degree",
      kind: "modified",
      label: "修改学位",
      sectionId: "education",
      itemId: "zju",
      before: "本科",
      after: "工学学士",
    },
  ]);
  const educationRendered = await renderMarkup(
    React.createElement(SectionItems, {
      itemDiffById: educationLookup.itemDiffById,
      layout,
      section: educationSection,
      settings,
      t: messages,
      enableContactLinks: false,
    }),
  );
  expect(educationRendered).toMatch(
    /data-resume-diff-path="sections\.education\.items\.zju\.degree"/,
  );
  expect(educationRendered).toMatch(
    /data-resume-field="major"><span>计算机科学与技术<\/span>/,
  );
});

it("marks list deletions without overlays and hides an emptied rich-text item", async () => {
  const deletionDiff: ResumeDraftDiff = {
    id: "diff-delete-highlight",
    operationId: "edit-delete-highlight",
    path: "sections.experience.items.tencent.highlights",
    kind: "modified",
    label: "删除冗余 bullet",
    sectionId: "experience",
    itemId: "tencent",
    before: ["保留", "删除原文"],
    after: ["保留"],
  };
  const deletionRendered = await renderMarkup(
    React.createElement(RichHighlights, {
      diffs: [deletionDiff],
      highlights: ["保留"],
    }),
  );
  expect(deletionRendered).toMatch(/resume-diff-field--whole/);
  expect(deletionRendered).toContain(">保留<");
  expect(deletionRendered).not.toContain("删除原文");
  expect(deletionRendered).not.toMatch(
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|>−</,
  );

  const listDeletionRendered = await renderMarkup(
    React.createElement(RichListDiff, {
      diffs: [
        {
          ...deletionDiff,
          path: "sections.skills.items.skills.content",
          sectionId: "skills",
          itemId: "skills",
          before: "<ul><li>保留</li><li><strong>删除原文</strong></li></ul>",
          after: "<ul><li>保留</li></ul>",
        },
      ],
      html: "<ul><li>保留</li></ul>",
    }),
  );
  expect(listDeletionRendered).toMatch(/resume-diff-field--whole/);
  expect(listDeletionRendered).toContain(">保留<");
  expect(listDeletionRendered).not.toContain("删除原文");
  expect(listDeletionRendered).not.toMatch(
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|>−</,
  );

  const emptyHighlightRendered = await renderMarkup(
    React.createElement(RichHighlights, {
      diffs: [
        {
          ...deletionDiff,
          before: ["唯一一条"],
          after: [],
        },
      ],
      highlights: [],
    }),
  );
  expect(emptyHighlightRendered).not.toMatch(
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|tooltip-trigger|>−</,
  );

  const emptyListDiff = {
    ...deletionDiff,
    path: "sections.skills.items.skills.content",
    sectionId: "skills",
    itemId: "skills",
    before: "<ul><li>唯一一条</li></ul>",
    after: "",
  };
  const emptyListRendered = await renderMarkup(
    React.createElement(RichListDiff, {
      diffs: [emptyListDiff],
      html: "",
    }),
  );
  expect(emptyListRendered).not.toMatch(
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|tooltip-trigger|>−</,
  );

  expect(
    getRenderableItems({
      id: "skills",
      kind: "simple_list",
      layout: "list",
      title: "技能",
      items: [
        {
          id: "skills",
          title: "",
          subtitle: "",
          meta: "",
          period: "",
          description: "",
          highlights: [],
          content: "",
          url: "",
        },
      ],
    }).length,
  ).toBe(0);
});

it("renders surviving items without deleted-item anchors or overlays", async () => {
  const structuralLookup = createResumeDiffLookup([
    {
      id: "diff-delete-item",
      operationId: "delete-item",
      path: "sections.experience.items.second",
      kind: "deleted",
      label: "删除第二项",
      sectionId: "experience",
      itemId: "second",
      beforePreviousId: "first",
      beforeNextId: "third",
      before: { id: "second", company: "第二项", position: "工程师" },
    },
    {
      id: "diff-delete-education",
      operationId: "delete-education",
      path: "sections.education",
      kind: "deleted",
      label: "删除教育经历",
      sectionId: "education",
      beforeNextId: "experience",
      before: {
        id: "education",
        kind: "education",
        title: "教育经历",
        items: [],
      },
    },
  ]);
  expect(structuralLookup.itemDiffById.has("second")).toBe(false);
  const structuralItemRendered = await renderMarkup(
    React.createElement(SectionItems, {
      itemDiffById: structuralLookup.itemDiffById,
      layout,
      section: {
        id: "experience",
        kind: "experience",
        layout: "timeline",
        title: "工作经历",
        items: [
          {
            id: "first",
            title: "第一项",
            subtitle: "",
            meta: "",
            period: "",
            description: "",
            highlights: [],
            content: "",
            url: "",
          },
          {
            id: "third",
            title: "第三项",
            subtitle: "",
            meta: "",
            period: "",
            description: "",
            highlights: [],
            content: "",
            url: "",
          },
        ],
      },
      settings,
      t: messages,
      enableContactLinks: false,
    }),
  );
  expect(structuralItemRendered).toMatch(/第一项[\s\S]*第三项/);
  expect(structuralItemRendered).not.toMatch(
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|tooltip-trigger|>−</,
  );
});
