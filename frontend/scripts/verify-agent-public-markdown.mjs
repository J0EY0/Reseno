import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const server = await createServer({
  cacheDir: createViteTestCacheDir("agent-public-markdown"),
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
  const { default: zhMessages } = await server.ssrLoadModule(
    "/src/i18n/locales/zh.json",
  );
  const { MessageResponse } = await server.ssrLoadModule(
    "/src/components/ai-elements/message-response.tsx",
  );
  const { AgentAssistantResponse } = await server.ssrLoadModule(
    "/src/components/copilot/copilot-assistant-response.tsx",
  );
  const {
    createAgentMarkdownComponents,
    getAgentMarkdownFallbackText,
  } = await server.ssrLoadModule(
    "/src/lib/agent-markdown-presentation.tsx",
  );
  const { getAgentDisplayFieldLabels } = await server.ssrLoadModule(
    "/src/lib/agent-message-rendering.ts",
  );

  const edits = [
    {
      id: "edit-resume",
      title: "修复字段错位并匹配岗位",
      target: "resume",
      reason: "让简历内容更准确",
      diffs: [
        { path: "basic.summary", label: "个人简介" },
        {
          path: "sections.experience.items.item-1.company",
          label: "企业",
        },
        {
          path: "sections.experience.items.item-1.position",
          label: "职位",
        },
        {
          path: "sections.experience.items.item-1.location",
          label: "地点",
        },
        {
          path: "sections.experience.items.item-1.description",
          label: "工作描述",
        },
        {
          path: "sections.project.items.item-2.name",
          label: "项目名称",
        },
        {
          path: "sections.project.items.item-2.techStack",
          label: "技术栈",
        },
        {
          path: "sections.project.items.item-2.role",
          label: "项目角色",
        },
        {
          path: "sections.project.items.item-2.description",
          label: "项目描述",
        },
        {
          path: "sections.education.items.item-3.degree",
          label: "学历",
        },
        {
          path: "sections.education.items.item-3.major",
          label: "专业",
        },
      ],
    },
  ];
  const labels = getAgentDisplayFieldLabels(edits, zhMessages.fieldLabels);

  assert.equal(labels.get("basic.summary"), "个人简介");
  assert.equal(labels.get("company"), "企业");
  assert.equal(labels.get("techStack"), "技术栈");
  assert.equal(
    labels.get("description"),
    "描述",
    "A field used by multiple section types needs a neutral visible label.",
  );

  const markdown = `**字段错位修复：**

实习项：\`company\` 改为「腾讯」，\`position\` 改为「前端开发实习生」，\`location\` 清空；将“企业协同产品线”移入 \`description\`。

项目项：\`name\` 改为「ResuMate AI Agent简历制作网站」，技术栈拆分至 \`techStack\`，\`role\` 清空。

教育项：把“计算机科学与技术”从 \`degree\` 移到 \`major\`，\`degree\` 简化为「本科」。

**匹配度改写：**

\`basic.summary\`：收紧为前端方向 + React/TS 项目经验。

项目 \`description\`：保留实时编辑与 A4 纸张预览。

真正的代码示例 \`React.FC\` 应继续按代码显示。`;
  const markup = renderToStaticMarkup(
    createElement(MessageResponse, {
      children: markdown,
      components: createAgentMarkdownComponents(labels),
      mode: "static",
    }),
  );
  const assistantMarkup = renderToStaticMarkup(
    createElement(AgentAssistantResponse, {
      fieldLabels: labels,
      sources: undefined,
      text: markdown,
    }),
  );
  const assistantVisibleText = assistantMarkup.replace(/<[^>]*>/g, "");
  const fallbackText = getAgentMarkdownFallbackText(markdown, labels);

  for (const usefulText of [
    "字段错位修复",
    "腾讯",
    "前端开发实习生",
    "ResuMate AI Agent简历制作网站",
    "企业协同产品线",
    "A4 纸张预览",
    "匹配度改写",
    "React/TS 项目经验",
  ]) {
    assert.match(
      markup,
      new RegExp(usefulText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    );
  }

  for (const internalField of [
    "basic.summary",
    "company",
    "position",
    "location",
    "description",
    "name",
    "techStack",
    "role",
    "degree",
    "major",
  ]) {
    assert.doesNotMatch(
      markup,
      new RegExp(`>${internalField.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}<`),
    );
    assert.doesNotMatch(
      assistantVisibleText,
      new RegExp(internalField.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
      "The real assistant-response seam must not expose an internal field token.",
    );
    assert.doesNotMatch(
      fallbackText,
      new RegExp(`\`${internalField.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\``),
      "The lazy-render fallback must not flash an internal field token.",
    );
  }

  for (const usefulText of [
    "字段错位修复",
    "腾讯",
    "企业协同产品线",
    "匹配度改写",
    "A4 纸张预览",
  ]) {
    assert.match(
      assistantMarkup,
      new RegExp(usefulText),
      "The real assistant-response seam must preserve the useful answer.",
    );
  }

  for (const publicLabel of [
    "个人简介",
    "企业",
    "职位",
    "地点",
    "描述",
    "项目名称",
    "技术栈",
    "项目角色",
    "学历",
    "专业",
  ]) {
    assert.match(markup, new RegExp(`>${publicLabel}<`));
  }

  assert.match(
    markup,
    /<code[^>]*data-streamdown="inline-code"[^>]*>React\.FC<\/code>/,
    "Unrelated technical inline code must keep the standard code presentation.",
  );
} finally {
  await server.close();
}

console.log("Agent public Markdown checks passed.");
