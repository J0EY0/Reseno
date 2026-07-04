import type { AppMessages } from "@/i18n";
import type { ResumeData, ResumeSectionItem } from "@/types/resume";

function createAvatarPlaceholder(label: string) {
  const safeLabel = label.replaceAll('"', "&quot;");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="300" data-resumate-avatar-placeholder="true" data-placeholder-label="${safeLabel}"></svg>`;

  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function createPreviewItem(
  id: string,
  item: {
    title: string;
    subtitle?: string;
    meta?: string;
    period?: string;
    description?: string;
    highlights?: string[];
  },
): ResumeSectionItem {
  return {
    id,
    title: item.title,
    subtitle: item.subtitle ?? "",
    meta: item.meta ?? "",
    period: item.period ?? "",
    description: item.description ?? "",
    highlights: item.highlights ?? [],
  };
}

export function createTemplatePreviewResume(t: AppMessages): ResumeData {
  const sample = t.templatePreviewSample;

  // This fixture is only for template visual QA. It must stay outside template
  // settings and workspace persistence so preview controls never change user data.
  return {
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
        layout: "timeline",
        customTitle: "",
        items: [
          createPreviewItem("template-preview-education-1", sample.education),
        ],
      },
      {
        id: "template-preview-internship",
        kind: "internship",
        layout: "timeline",
        customTitle: "",
        items: [
          createPreviewItem(
            "template-preview-internship-1",
            sample.internship,
          ),
        ],
      },
      {
        id: "template-preview-project",
        kind: "project",
        layout: "timeline",
        customTitle: "",
        items: [
          createPreviewItem("template-preview-project-1", sample.projectPrimary),
          createPreviewItem(
            "template-preview-project-2",
            sample.projectSecondary,
          ),
        ],
      },
      {
        id: "template-preview-skills",
        kind: "skills",
        layout: "list",
        customTitle: "",
        items: sample.skills.map((item, index) =>
          createPreviewItem(`template-preview-skill-${index + 1}`, item),
        ),
      },
    ],
  };
}
