// @vitest-environment node
import type { ReactNode } from "react";
import { renderToReadableStream, renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MessageResponse } from "@/components/ai-elements/message-response";
import { AgentAssistantResponse } from "@/components/copilot/copilot-assistant-response";
import { AgentAssistantMessageRow } from "@/components/copilot/copilot-message-presentation";
import zh from "@/i18n/locales/zh.json";
import {
  createAgentMarkdownComponents,
  getAgentMarkdownFallbackText,
} from "@/lib/agent-markdown-presentation";
import { getAgentDisplayFieldLabels } from "@/lib/agent-message-rendering";
import type { AgentResumeEditSuggestion } from "@/types/api";

async function settledMarkup(element: ReactNode) {
  const stream = await renderToReadableStream(element);
  await stream.allReady;
  return new Response(stream).text();
}

const fields = [
  ["basic.summary", "个人简介"],
  ["sections.experience.items.item-1.company", "企业"],
  ["sections.experience.items.item-1.position", "职位"],
  ["sections.experience.items.item-1.location", "地点"],
  ["sections.experience.items.item-1.description", "工作描述"],
  ["sections.project.items.item-2.name", "项目名称"],
  ["sections.project.items.item-2.techStack", "技术栈"],
  ["sections.project.items.item-2.role", "项目角色"],
  ["sections.project.items.item-2.description", "项目描述"],
  ["sections.education.items.item-3.degree", "学历"],
  ["sections.education.items.item-3.major", "专业"],
];
const edits: AgentResumeEditSuggestion[] = [
  {
    id: "edit-resume",
    title: "修复字段错位并匹配岗位",
    target: "resume",
    reason: "让简历内容更准确",
    operation: {
      type: "replace_field",
      path: "basic.summary",
      value: "Updated summary",
    },
    diffs: fields.map(([path, label], index) => ({
      id: `diff-${index}`,
      operationId: "edit-resume",
      kind: "modified",
      path,
      label,
    })),
  },
];
const labels = getAgentDisplayFieldLabels(edits, zh.fieldLabels);

const markdown = `**字段错位修复：**

实习项：\`company\` 改为「腾讯」，\`position\` 改为「前端开发实习生」，\`location\` 清空；将“企业协同产品线”移入 \`description\`。

项目项：\`name\` 改为「Reseno AI Agent简历制作网站」，技术栈拆分至 \`techStack\`，\`role\` 清空。

教育项：把“计算机科学与技术”从 \`degree\` 移到 \`major\`，\`degree\` 简化为「本科」。

**匹配度改写：**

\`basic.summary\`：收紧为前端方向 + React/TS 项目经验。

项目 \`description\`：保留实时编辑与 A4 纸张预览。

真正的代码示例 \`React.FC\` 应继续按代码显示。`;
const comparisonTable = `**岗位要求对比：**

| JD 要求 | 简历证据 |
| --- | --- |
| React | Reseno 项目 |`;

describe("Agent public Markdown", () => {
  it.each([
    ["basic.summary", "个人简介"],
    ["company", "企业"],
    ["techStack", "技术栈"],
    ["description", "描述"],
  ])("projects field %s to the unambiguous public label %s", (field, label) => {
    expect(labels.get(field)).toBe(label);
  });

  it.each([true, false])(
    "renders Chinese text with streaming=%s",
    async (streaming) => {
      const text = "正在逐字展示这段中文回复";
      const markup = await settledMarkup(
        <AgentAssistantMessageRow
          t={zh}
          isStreamingAssistant={streaming}
          message={{
            id: "assistant-streaming-text",
            role: "assistant",
            text,
            response: {
              id: "assistant-streaming-text",
              role: "assistant",
              text,
              timeline: [
                {
                  id: "timeline-streaming-text",
                  type: "text",
                  text,
                  toolIds: [],
                },
              ],
            },
          }}
        />,
      );
      expect(markup.replace(/<[^>]*>/g, "")).toContain(text);
      if (streaming) {
        expect(
          [...markup.matchAll(/data-sd-animate="true"/g)].length,
        ).toBeGreaterThanOrEqual(4);
        for (const setting of [
          "--sd-animation:sd-fadeIn",
          "--sd-duration:120ms",
          "--sd-easing:ease-out",
          "--sd-delay:8ms",
        ]) {
          expect(markup).toContain(setting);
        }
      } else {
        expect(markup).not.toMatch(/data-sd-animate/);
      }
    },
  );

  it("keeps answer content and technical code while replacing internal fields in rich and fallback text", async () => {
    const markup = renderToStaticMarkup(
      <MessageResponse
        components={createAgentMarkdownComponents(labels)}
        mode="static"
      >
        {markdown}
      </MessageResponse>,
    );
    const assistantMarkup = await settledMarkup(
      <AgentAssistantResponse
        t={zh}
        fieldLabels={labels}
        sources={undefined}
        text={markdown}
      />,
    );
    const assistantText = assistantMarkup.replace(/<[^>]*>/g, "");
    const fallback = getAgentMarkdownFallbackText(markdown, labels);
    for (const text of [
      "字段错位修复",
      "腾讯",
      "前端开发实习生",
      "Reseno AI Agent简历制作网站",
      "企业协同产品线",
      "A4 纸张预览",
      "匹配度改写",
      "React/TS 项目经验",
    ]) {
      expect(markup).toContain(text);
      expect(assistantMarkup).toContain(text);
      expect(fallback).toContain(text);
    }
    for (const field of [
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
      expect(markup).not.toContain(`>${field}<`);
      expect(assistantText).not.toContain(field);
      expect(fallback).not.toContain(`\`${field}\``);
    }
    for (const label of [
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
      expect(markup).toContain(`>${label}<`);
    }
    expect(markup).toMatch(
      /<code[^>]*data-streamdown="inline-code"[^>]*>React\.FC<\/code>/,
    );
  });

  it("keeps a GFM comparison table visible when the assistant also carries edits", async () => {
    const direct = renderToStaticMarkup(
      <MessageResponse mode="static">{comparisonTable}</MessageResponse>,
    );
    const markup = await settledMarkup(
      <AgentAssistantMessageRow
        t={zh}
        isStreamingAssistant={false}
        message={{
          id: "assistant-with-edits",
          role: "assistant",
          text: comparisonTable,
          response: {
            id: "assistant-with-edits",
            role: "assistant",
            text: comparisonTable,
            edits,
            transactionState: "committed",
          },
        }}
      />,
    );
    expect(direct).toMatch(/<table(?:\s|>)/);
    expect(markup).toMatch(/<table(?:\s|>)/);
    for (const text of ["JD 要求", "简历证据", "React", "Reseno 项目"])
      expect(markup).toContain(text);
  });
});
