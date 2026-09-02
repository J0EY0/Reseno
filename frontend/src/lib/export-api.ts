import { apiRoutes, fetchApiResource, requestApi } from "@/lib/api-client";
import { isBuiltinTemplateId } from "@/lib/template-presets";
import type {
  ExportResumeImagesRequest,
  ExportResumeImagesResponse,
  ExportResumePdfRequest,
  ExportResumePdfResponse,
  ResumeArtifactItem,
  ResumeArtifactV1,
} from "@/types/api";
import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

interface DownloadableExport {
  downloadUrl: string;
  fileName: string;
}

export async function requestResumePdfExport(
  request: ExportResumePdfRequest,
) {
  return requestApi<ExportResumePdfResponse>(apiRoutes.resumePdfExport, {
    body: request,
    method: "POST",
  });
}

export async function requestResumeImagesExport(
  request: ExportResumeImagesRequest,
) {
  return requestApi<ExportResumeImagesResponse>(apiRoutes.resumeImagesExport, {
    body: request,
    method: "POST",
  });
}

function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = fileName;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function downloadExportedFile(result: DownloadableExport) {
  const response = await fetchApiResource(result.downloadUrl);
  const blob = await response.blob();
  downloadBlob(blob, result.fileName);
}

export async function downloadExportedPdf(result: ExportResumePdfResponse) {
  await downloadExportedFile(result);
}

function createTemplateArtifactDefinition(
  template: ResumeTemplateDefinition,
) {
  return {
    preset: template.preset,
    name: template.name,
    description: template.description,
    layout: template.layout,
    typography: template.typography,
    settings: template.settings,
  };
}

export function createResumeArtifact(
  resume: ResumeWorkspaceItem,
  templateDefinition: ResumeTemplateDefinition,
): ResumeArtifactV1 {
  const templateId = resume.template;
  const isBuiltInTemplate = isBuiltinTemplateId(templateId);

  if (!isBuiltInTemplate && templateDefinition.id !== templateId) {
    throw new Error("The resume's custom template definition is unavailable.");
  }

  const exportDocument: ResumeArtifactItem = {
    title: resume.title,
    documentLocale: resume.documentLocale,
    resume: resume.resume,
    jobBrief: resume.jobBrief,
    typography: resume.typography,
    template: isBuiltInTemplate ? templateId : "custom:0",
    templateSettings: resume.templateSettings ?? null,
  };

  return {
    format: "resumate.resume",
    formatVersion: 1,
    templates: isBuiltInTemplate
      ? []
      : [
          {
            ref: "custom:0",
            definition: createTemplateArtifactDefinition(templateDefinition),
          },
        ],
    resumes: [exportDocument],
  };
}

export function downloadResumeJson(
  resume: ResumeWorkspaceItem,
  templateDefinition: ResumeTemplateDefinition,
) {
  const artifact = createResumeArtifact(resume, templateDefinition);
  const normalizedName = resume.title
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .split("")
    .filter((character) => character.charCodeAt(0) >= 32)
    .join("")
    .replace(/^[ ._-]+|[ ._-]+$/g, "");
  const fileName = `${normalizedName || "resume"}.json`;
  const json = `${JSON.stringify(artifact, null, 2)}\n`;

  downloadBlob(
    new Blob([json], { type: "application/json;charset=utf-8" }),
    fileName,
  );
}
