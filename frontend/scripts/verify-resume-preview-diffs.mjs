import assert from "node:assert/strict";
import React from "react";
import { renderToReadableStream } from "react-dom/server";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const server = await createServer({
  cacheDir: createViteTestCacheDir("resume-preview-diffs"),
  configFile: false,
  logLevel: "error",
  optimizeDeps: { noDiscovery: true },
  root: process.cwd(),
  server: { hmr: false, middlewareMode: true, ws: false },
  resolve: {
    alias: { "@": new URL("../src", import.meta.url).pathname },
  },
});

try {
  const { getRenderableFieldDiffs } =
    await server.ssrLoadModule(
    "/src/components/preview/resume-preview-diffs.ts",
  );
  const { createResumeDiffLookup } = await server.ssrLoadModule(
    "/src/components/preview/resume-preview-diff-lookup.ts",
  );
  const { getRenderableItems } = await server.ssrLoadModule(
    "/src/components/preview/resume-preview-model.ts",
  );
  const {
    createInlineDiffParts,
    createListDiff,
  } =
    await server.ssrLoadModule(
      "/src/components/preview/resume-preview-diff-algorithms.ts",
    );

  const lookup = createResumeDiffLookup([
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
  const itemDiff = lookup.itemDiffById.get("tencent");

  assert(itemDiff, "The changed item must be addressable by item id.");
  assert.equal(
    itemDiff.structuralDiff,
    undefined,
    "Field edits must not be promoted to a whole-item structural diff.",
  );
  assert.deepEqual(
    [...itemDiff.fieldDiffByName.keys()],
    ["position", "description", "highlights"],
    "Every changed field must remain independently addressable.",
  );
  assert.deepEqual(itemDiff.fieldDiffByName.get("position"), {
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
  assert.equal(
    revertedLookup.basicDiffByField.size,
    0,
    "A field restored to its original value must not remain highlighted.",
  );
  assert.equal(
    getRenderableFieldDiffs(itemDiff, "experience", "title").length,
    0,
    "An unchanged company title must not be highlighted.",
  );
  assert.deepEqual(
    getRenderableFieldDiffs(itemDiff, "experience", "subtitle").map(
      (diff) => diff.path,
    ),
    ["sections.experience.items.tencent.position"],
    "Only the position slot must receive the position diff.",
  );

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
  assert.deepEqual(
    {
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
      meta: getRenderableFieldDiffs(
        publicationLookup,
        "publication",
        "meta",
      ).map((diff) => diff.path),
    },
    {
      title: ["sections.publications.items.paper-1.title"],
      subtitle: ["sections.publications.items.paper-1.authors"],
      meta: ["sections.publications.items.paper-1.venue"],
    },
    "Publication diffs must highlight the matching citation slots.",
  );
  assert.deepEqual(
    [...createListDiff(
      ["第一条不变", "第二条旧文本"],
      ["第一条不变", "第二条新文本"],
    ).changedIndices],
    [1],
    "A one-bullet rewrite must not highlight unchanged bullets.",
  );
  assert.deepEqual(
    [...createListDiff(["保留", "删除"], ["保留"]).changedIndices],
    [],
    "A deletion-only list diff must not falsely mark an unchanged remaining bullet.",
  );
  assert.equal(
    createListDiff(["保留", "删除原文"], ["保留"]).hasDeletions,
    true,
    "A deletion-only list diff must retain a quiet deletion state without rendering deleted text over the candidate.",
  );

  const inlineParts = createInlineDiffParts(
    "负责编辑器表单模块重构，页面状态管理复杂度显著下降。",
    "负责编辑器表单模块重构，显著降低页面状态管理复杂度。",
  );
  assert.equal(
    inlineParts.map((part) => part.value).join(""),
    "负责编辑器表单模块重构，显著降低页面状态管理复杂度。",
    "Inline diff parts must reproduce the candidate text exactly.",
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
  assert.equal(
    deletionOnlyInlineParts.map((part) => part.value).join(""),
    "负责前端架构设计",
    "A deletion-only inline diff must still reproduce the candidate text exactly.",
  );
  assert.equal(
    deletionOnlyInlineParts.some((part) => part.changed),
    false,
    "A deletion-only inline diff must not synthesize an added fragment.",
  );

  const { ResumeDiffText } = await server.ssrLoadModule(
    "/src/components/preview/resume-preview-diff-text.tsx",
  );
  for (const [before, after] of [
    ["Engineer", "<p><strong>Engineer</strong></p>"],
    ["<p><strong>Engineer</strong></p>", "Engineer"],
  ]) {
    const formatStream = await renderToReadableStream(
      React.createElement(ResumeDiffText, {
        richText: true,
        value: after,
        diffs: [{
          id: "format-position",
          operationId: "format-position",
          path: "sections.experience.items.tencent.position",
          kind: "modified",
          label: "Format position",
          before,
          after,
        }],
      }),
    );
    await formatStream.allReady;
    const formatRendered = await new Response(formatStream).text();
    assert.match(formatRendered, /resume-diff-field--whole/);
    assert.match(formatRendered, /data-resume-diff-path="sections\.experience\.items\.tencent\.position"/);
    assert.doesNotMatch(formatRendered, /&lt;(?:p|strong)&gt;/);
  }

  const clearedFieldStream = await renderToReadableStream(
    React.createElement(ResumeDiffText, {
      value: "",
      diffs: [{
        id: "diff-clear-summary",
        operationId: "edit-clear-summary",
        path: "basic.summary",
        kind: "modified",
        label: "清空个人总结",
        before: "原个人总结",
        after: "",
      }],
    }),
  );
  await clearedFieldStream.allReady;
  const clearedFieldRendered = await new Response(clearedFieldStream).text();
  assert.match(
    clearedFieldRendered,
    /data-resume-diff-path="basic\.summary"/,
    "Clearing a scalar field must retain its canonical review path.",
  );
  assert.doesNotMatch(
    clearedFieldRendered,
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|>−</,
    "Clearing a scalar field must not place an overlay control beside other text.",
  );

  const deletionOnlyTextStream = await renderToReadableStream(
    React.createElement(ResumeDiffText, {
      value: "负责前端架构设计",
      diffs: [{
        id: "diff-remove-words",
        operationId: "edit-remove-words",
        path: "sections.experience.items.tencent.description",
        kind: "modified",
        label: "精简描述",
        sectionId: "experience",
        itemId: "tencent",
        before: "负责复杂的前端架构设计",
        after: "负责前端架构设计",
      }],
    }),
  );
  await deletionOnlyTextStream.allReady;
  const deletionOnlyTextRendered = await new Response(
    deletionOnlyTextStream,
  ).text();
  assert.match(
    deletionOnlyTextRendered,
    /resume-diff-field--whole/,
    "A deletion-only rewrite must use a quiet field marker when no added text remains to highlight.",
  );
  assert.doesNotMatch(
    deletionOnlyTextRendered,
    /resume-diff-deletion-marker|resume-diff-inline-deletion|data-resume-diff-deletion-boundary|>−</,
    "Removing words from a non-empty field must not overlay an interactive deletion marker on live text.",
  );

  const { SectionItems } = await server.ssrLoadModule(
    "/src/components/preview/resume-preview-section-items.tsx",
  );
  const renderedStream = await renderToReadableStream(
    React.createElement(SectionItems, {
      itemDiffById: lookup.itemDiffById,
      layout: {
        listItemLayout: "stacked",
        timelineItemLayout: "split",
      },
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
      settings: {
        bodyColor: "#334155",
        bodyLineHeight: 1.6,
        bodyScale: 1,
        itemGap: 1,
        itemTitleScale: 1.1,
        metaScale: 0.9,
      },
      t: {
        agentDiffAdded: "已新增",
        agentDiffDeleted: "已删除",
        agentDiffModified: "已修改",
        agentDiffMoved: "已移动",
      },
    }),
  );
  await renderedStream.allReady;
  const rendered = await new Response(renderedStream).text();
  assert.doesNotMatch(
    rendered,
    /resume-diff--modified/,
    "A field edit must never tint the whole timeline item.",
  );
  assert.match(
    rendered,
    /data-resume-diff-label="已修改"/,
    "A field edit must keep the visible modified status badge on its resume item.",
  );
  assert.match(
    rendered,
    /<h3[^>]*><span>腾讯<\/span><\/h3>/,
    "The unchanged company must render without a diff marker.",
  );
  assert.match(
    rendered,
    /data-resume-diff-path="sections\.experience\.items\.tencent\.position"/,
    "The changed position must expose its exact canonical path.",
  );
  assert.match(
    rendered,
    /<li(?: class="")?><span>第一条不变<\/span><\/li><li class="resume-diff-field resume-diff-field--whole"[^>]*><span>第二条新文本<\/span><\/li>/,
    "Only the rewritten bullet must be visually marked.",
  );

  const clearedPositionLookup = createResumeDiffLookup([{
    id: "diff-clear-position",
    operationId: "edit-clear-position",
    path: "sections.experience.items.tencent.position",
    kind: "modified",
    label: "清空职位",
    sectionId: "experience",
    itemId: "tencent",
    before: "前端开发实习生",
    after: "",
  }]);
  const clearedPositionStream = await renderToReadableStream(
    React.createElement(SectionItems, {
      itemDiffById: clearedPositionLookup.itemDiffById,
      layout: { listItemLayout: "stacked", timelineItemLayout: "split" },
      section: {
        id: "experience",
        kind: "experience",
        layout: "timeline",
        title: "工作经历",
        items: [{
          id: "tencent",
          title: "腾讯",
          subtitle: "",
          meta: "",
          period: "",
          description: "",
          highlights: [],
          content: "",
          url: "",
        }],
      },
      settings: {
        bodyColor: "#334155",
        bodyLineHeight: 1.6,
        bodyScale: 1,
        itemGap: 1,
        itemTitleScale: 1.1,
        metaScale: 0.9,
      },
      t: {
        agentDiffAdded: "已新增",
        agentDiffDeleted: "已删除",
        agentDiffModified: "已修改",
        agentDiffMoved: "已移动",
      },
    }),
  );
  await clearedPositionStream.allReady;
  const clearedPositionRendered = await new Response(clearedPositionStream).text();
  assert.match(
    clearedPositionRendered,
    /data-resume-diff-path="sections\.experience\.items\.tencent\.position"/,
    "Clearing a subtitle field must retain an exact deletion marker in the empty slot.",
  );

  const { projectResumeSection } = await server.ssrLoadModule(
    "/src/lib/resume-sections.ts",
  );
  const educationSection = projectResumeSection({
    id: "education",
    kind: "education",
    title: "教育经历",
    items: [{
      id: "zju",
      school: "浙江大学",
      degree: "工学学士",
      major: "计算机科学与技术",
      gpa: "3.85 / 4.0",
      location: "杭州",
      period: "2019.09 - 2023.06",
      description: "",
      highlights: [],
    }],
  });
  const educationLookup = createResumeDiffLookup([{
    id: "diff-degree",
    operationId: "edit-degree",
    path: "sections.education.items.zju.degree",
    kind: "modified",
    label: "修改学位",
    sectionId: "education",
    itemId: "zju",
    before: "本科",
    after: "工学学士",
  }]);
  const educationStream = await renderToReadableStream(
    React.createElement(SectionItems, {
      itemDiffById: educationLookup.itemDiffById,
      layout: { listItemLayout: "stacked", timelineItemLayout: "split" },
      section: educationSection,
      settings: {
        bodyColor: "#334155",
        bodyLineHeight: 1.6,
        bodyScale: 1,
        itemGap: 1,
        itemTitleScale: 1.1,
        metaScale: 0.9,
      },
      t: {
        agentDiffAdded: "已新增",
        agentDiffDeleted: "已删除",
        agentDiffModified: "已修改",
        agentDiffMoved: "已移动",
      },
    }),
  );
  await educationStream.allReady;
  const educationRendered = await new Response(educationStream).text();
  assert.match(
    educationRendered,
    /data-resume-diff-path="sections\.education\.items\.zju\.degree"/,
    "An education degree change must expose the exact degree path.",
  );
  assert.match(
    educationRendered,
    /data-resume-field="major"><span>计算机科学与技术<\/span>/,
    "The unchanged education major must remain a separate unhighlighted field.",
  );

  const { RichHighlights, RichListDiff } = await server.ssrLoadModule(
    "/src/components/preview/resume-preview-rich-diff.tsx",
  );
  const deletionDiff = {
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
  const deletionStream = await renderToReadableStream(
    React.createElement(RichHighlights, {
      diffs: [deletionDiff],
      highlights: ["保留"],
    }),
  );
  await deletionStream.allReady;
  const deletionRendered = await new Response(deletionStream).text();
  assert.match(
    deletionRendered,
    /resume-diff-field--whole/,
    "A deletion-only bullet change must mark the field without overlaying surviving text.",
  );
  assert.doesNotMatch(
    deletionRendered,
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|>−</,
    "Deleting a bullet must not overlay a control on the surviving list.",
  );

  const listDeletionStream = await renderToReadableStream(
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
  await listDeletionStream.allReady;
  const listDeletionRendered = await new Response(listDeletionStream).text();
  assert.match(
    listDeletionRendered,
    /resume-diff-field--whole/,
    "A deletion-only simple-list change must mark the field without overlaying surviving text.",
  );
  assert.doesNotMatch(
    listDeletionRendered,
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|>−</,
    "A simple-list deletion must not overlay a control on the surviving list.",
  );

  const emptyHighlightStream = await renderToReadableStream(
    React.createElement(RichHighlights, {
      diffs: [{
        ...deletionDiff,
        before: ["唯一一条"],
        after: [],
      }],
      highlights: [],
    }),
  );
  await emptyHighlightStream.allReady;
  const emptyHighlightRendered = await new Response(emptyHighlightStream).text();
  assert.doesNotMatch(
    emptyHighlightRendered,
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|tooltip-trigger|>−</,
    "Deleting the only highlight must leave review details to the change summary instead of creating an empty overlay.",
  );

  const emptyListDiff = {
    ...deletionDiff,
    path: "sections.skills.items.skills.content",
    sectionId: "skills",
    itemId: "skills",
    before: "<ul><li>唯一一条</li></ul>",
    after: "",
  };
  const emptyListStream = await renderToReadableStream(
    React.createElement(RichListDiff, {
      diffs: [emptyListDiff],
      html: "",
    }),
  );
  await emptyListStream.allReady;
  const emptyListRendered = await new Response(emptyListStream).text();
  assert.doesNotMatch(
    emptyListRendered,
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|tooltip-trigger|>−</,
    "Clearing a simple list must leave review details to the change summary instead of creating an empty overlay.",
  );

  const emptyListLookup = createResumeDiffLookup([emptyListDiff]);
  assert.equal(
    getRenderableItems(
      {
        id: "skills",
        kind: "simple_list",
        layout: "list",
        title: "技能",
        items: [{
          id: "skills",
          title: "",
          subtitle: "",
          meta: "",
          period: "",
          description: "",
          highlights: [],
          content: "",
          url: "",
        }],
      },
      emptyListLookup.itemDiffById,
    ).length,
    0,
    "An emptied simple-list item must not create a blank preview row solely for review metadata.",
  );

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
  assert.equal(
    structuralLookup.itemDiffById.has("second"),
    false,
    "Deleted items must not create invisible preview anchors or overlay controls.",
  );
  const structuralItemStream = await renderToReadableStream(
    React.createElement(SectionItems, {
      itemDiffById: structuralLookup.itemDiffById,
      layout: {
        listItemLayout: "stacked",
        timelineItemLayout: "split",
      },
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
      settings: {
        bodyColor: "#334155",
        bodyLineHeight: 1.6,
        bodyScale: 1,
        itemGap: 1,
        itemTitleScale: 1.1,
        metaScale: 0.9,
      },
      t: {
        agentDiffAdded: "已新增",
        agentDiffDeleted: "已删除",
        agentDiffModified: "已修改",
        agentDiffMoved: "已移动",
      },
    }),
  );
  await structuralItemStream.allReady;
  const structuralItemRendered = await new Response(
    structuralItemStream,
  ).text();
  assert.match(
    structuralItemRendered,
    /第一项[\s\S]*第三项/,
    "The candidate preview must keep rendering surviving items after a structural deletion.",
  );
  assert.doesNotMatch(
    structuralItemRendered,
    /resume-diff-deletion-marker|data-resume-diff-deleted-text|tooltip-trigger|>−</,
    "Structural deletions must not create overlay controls in the candidate preview.",
  );
} finally {
  await server.close();
}

console.log("Resume preview field and inline diff checks passed.");
