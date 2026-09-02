import { importResumePayload } from "@/lib/import-api";
import { normalizeResumeTitle } from "@/lib/resume-title";
import {
  createResumeApi,
  createTemplateApi,
} from "@/lib/workspace-api";
import type { ResumeDetailResponse } from "@/types/api";
import type { ResumeTemplateDefinition } from "@/types/resume";

export async function importResumesIntoWorkspace(file: File) {
  const isPdfImport =
    file.type === "application/pdf" ||
    file.name.toLowerCase().endsWith(".pdf");
  if (isPdfImport) {
    // The parser and PDF.js are loaded only after PDF intent is known.
    const { importResumeFromPdf } = await import("@/lib/pdf-resume-import");
    const { documentLocale, resume } = await importResumeFromPdf(file);
    const result = await createResumeApi({
      documentLocale,
      jobBrief: "",
      resume,
      title: normalizeResumeTitle(
        file.name.replace(/\.pdf$/i, ""),
        documentLocale === "zh" ? "简历" : "Resume",
      ),
      templateSettings: null,
    });

    return {
      savedImports: [result],
      savedTemplates: [],
    };
  }

  const importedBundle = await importResumePayload(file);
  if (importedBundle.resumes.length === 0) {
    throw new Error("No valid resume documents found in the imported file.");
  }

  const templateIdByArtifactRef = new Map<string, string>();
  const savedTemplates: ResumeTemplateDefinition[] = [];
  for (const embeddedTemplate of importedBundle.templates) {
    const result = await createTemplateApi(embeddedTemplate.definition);
    templateIdByArtifactRef.set(embeddedTemplate.ref, result.template.id);
    savedTemplates.push(result.template);
  }

  const savedImports: ResumeDetailResponse[] = [];
  for (const item of importedBundle.resumes) {
    const mappedTemplateId = templateIdByArtifactRef.get(item.template);
    if (item.template.startsWith("custom:") && !mappedTemplateId) {
      throw new Error("Imported resume references an unknown template.");
    }
    savedImports.push(
      await createResumeApi({
        documentLocale: item.documentLocale,
        title: item.title,
        resume: item.resume,
        jobBrief: item.jobBrief,
        typography: item.typography,
        template: mappedTemplateId ?? item.template,
        templateSettings: item.templateSettings ?? null,
      }),
    );
  }

  return { savedImports, savedTemplates };
}
