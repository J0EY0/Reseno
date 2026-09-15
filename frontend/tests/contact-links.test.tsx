import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ResumeThumbnail } from "@/components/preview/resume-thumbnail";
import { defaultMessages } from "@/i18n";
import {
  createContactHref,
  normalizeContactFieldType,
} from "@/lib/contact-links";
import { createEmptyResume } from "@/lib/resume";
import { getBuiltInTemplates, getTemplateById } from "@/lib/templates";

describe("Contact links", () => {
  it.each([
    ["url", "url"],
    ["javascript", "text"],
  ])("normalizes field type %j to %j", (value, expected) => {
    expect(normalizeContactFieldType(value)).toBe(expected);
  });

  it.each([
    ["text", "https://example.com", null],
    ["email", "name@example.com", "mailto:name@example.com"],
    ["phone", "+86 13800000000", "tel:+86 13800000000"],
    ["url", "github.com/example", "https://github.com/example"],
    ["url", "http://example.com/profile", "http://example.com/profile"],
    ["url", "javascript:alert(1)", null],
    ["url", "data:text/html,test", null],
    ["url", "ftp://example.com/file", null],
    ["email", "https://example.com", null],
    ["phone", "mailto:name@example.com", null],
    ["url", "https://", null],
    ["url", "https://example.com\nunsafe", null],
  ] as const)("builds %s links for %j", (type, value, expected) => {
    expect(createContactHref(type, value)).toBe(expected);
  });

  it("renders contact and project text without anchors inside a linked thumbnail", () => {
    const resume = createEmptyResume();
    resume.basic = {
      ...resume.basic,
      name: "Example",
      phone: "+86 13800000000",
      email: "name@example.com",
    };
    const project = resume.sections.find(
      (section) => section.kind === "project",
    )!;
    project.title = "Projects";
    project.items[0] = {
      ...project.items[0],
      name: "Linked project",
      role: "Lead",
      period: "2026",
      url: "https://example.com/project",
    };
    resume.sections = [project];
    const template = getTemplateById(
      getBuiltInTemplates(defaultMessages),
      "minimal",
    );
    const markup = renderToStaticMarkup(
      <a href="/resume/example">
        <ResumeThumbnail
          t={defaultMessages}
          resume={resume}
          template={template}
          fontFamily="inter"
          fontSize={16}
        />
      </a>,
    );

    expect(markup.match(/<a(?:\s|>)/g)).toHaveLength(1);
    for (const content of [
      resume.basic.name,
      resume.basic.phone,
      resume.basic.email,
      project.items[0].name,
      project.items[0].url,
    ]) {
      expect(markup).toContain(content);
    }
  });
});
