import { createEmptyResume } from "@/lib/resume";
import { getBuiltinTemplatePreset } from "@/lib/template-presets";
import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

export function createResumeDetailItem(
  overrides: Partial<ResumeWorkspaceItem> = {},
): ResumeWorkspaceItem {
  const resume = overrides.resume ?? createEmptyResume();
  return {
    id: "resume-a",
    title: "Original title",
    updatedAt: "2026-09-01T00:00:00.000Z",
    documentLocale: "en",
    jobBrief: "Original job brief",
    template: "minimal",
    templateSettings: null,
    typography: { fontFamily: "inter", fontSize: 16 },
    resume: {
      ...resume,
      basic: { ...resume.basic, name: "Ada", headline: "Engineer" },
      sections: [],
    },
    ...structuredClone(overrides),
  };
}

export function createResumeDetailTemplate(
  id: string,
  overrides: Partial<ResumeTemplateDefinition> = {},
): ResumeTemplateDefinition {
  const preset = structuredClone(getBuiltinTemplatePreset("minimal"));
  return {
    ...preset,
    id,
    name: id,
    preset: "minimal",
    description: "",
    updatedAt: "2026-09-01T00:00:00.000Z",
    isBuiltIn: false,
    layout: { ...preset.layout, images: [] },
    ...structuredClone(overrides),
  };
}
