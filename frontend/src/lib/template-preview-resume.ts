import type { AppMessages } from "@/i18n";
import { serializeListItemsToHtml } from "@/lib/rich-text";
import type { ResumeData } from "@/types/resume";

function createAvatarPlaceholder(label: string) {
  const safeLabel = label.replaceAll('"', "&quot;");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="300" data-resumate-avatar-placeholder="true" data-placeholder-label="${safeLabel}"></svg>`;

  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export function createTemplatePreviewResume(t: AppMessages): ResumeData {
  const sample = t.templatePreviewSample;

  // This fixture is only for template visual QA. It must stay outside template
  // settings and workspace persistence so preview controls never change user data.
  return {
    schemaVersion: 2,
    basic: {
      name: sample.basic.name,
      headline: sample.basic.headline,
      phone: sample.basic.phone,
      email: sample.basic.email,
      location: sample.basic.location,
      avatar: createAvatarPlaceholder(t.resumePreviewAvatarPlaceholder),
      summary: sample.basic.summary,
      customFields: [],
    },
    // Keep the built-in preview dense but bounded: it should feel like a real
    // one-page resume while still fitting every built-in template preset.
    sections: [
      {
        id: "template-preview-education",
        kind: "education",
        title: "",
        items: [
          {
            id: "template-preview-education-1",
            school: sample.education.title,
            degree: sample.education.subtitle,
            major: "",
            gpa: sample.education.meta,
            location: "",
            period: sample.education.period,
            description: "",
            highlights: sample.education.highlights,
          },
        ],
      },
      {
        id: "template-preview-internship",
        kind: "experience",
        title: "",
        items: [
          {
            id: "template-preview-internship-1",
            company: sample.internship.title,
            position: sample.internship.subtitle,
            location: sample.internship.meta,
            period: sample.internship.period,
            description: "",
            highlights: sample.internship.highlights,
          },
        ],
      },
      {
        id: "template-preview-project",
        kind: "project",
        title: "",
        items: [
          {
            id: "template-preview-project-1",
            name: sample.projectPrimary.title,
            role: sample.projectPrimary.subtitle,
            techStack: sample.projectPrimary.meta.split(/\s*[/,]\s*/),
            period: sample.projectPrimary.period,
            url: "",
            description: "",
            highlights: sample.projectPrimary.highlights,
          },
          {
            id: "template-preview-project-2",
            name: sample.projectSecondary.title,
            role: sample.projectSecondary.subtitle,
            techStack: sample.projectSecondary.meta.split(/\s*[/,]\s*/),
            period: sample.projectSecondary.period,
            url: "",
            description: "",
            highlights: sample.projectSecondary.highlights,
          },
        ],
      },
      {
        id: "template-preview-skills",
        kind: "simple_list",
        title: t.defaultOtherSkill,
        items: [
          {
            id: "template-preview-skills-content",
            content: serializeListItemsToHtml(
              sample.skills.map((item) => `${item.title}：${item.subtitle}`),
            ),
          },
        ],
      },
    ],
  };
}
