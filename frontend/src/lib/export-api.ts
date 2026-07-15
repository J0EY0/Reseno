import { apiRoutes, fetchApiResource, requestApi } from "@/lib/api-client";
import type {
  ExportResumeImagesRequest,
  ExportResumeImagesResponse,
  ExportResumePdfRequest,
  ExportResumePdfResponse,
} from "@/types/api";
import type { ResumeWorkspaceItem } from "@/types/resume";

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

export function downloadResumeJson(resume: ResumeWorkspaceItem) {
  const exportDocument = {
    id: resume.id,
    title: resume.title,
    updatedAt: resume.updatedAt,
    resume: resume.resume,
    typography: resume.typography,
    template: resume.template,
    templateSettings: resume.templateSettings,
  };
  const normalizedName = resume.title
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .split("")
    .filter((character) => character.charCodeAt(0) >= 32)
    .join("")
    .replace(/^[ ._-]+|[ ._-]+$/g, "");
  const fileName = `${normalizedName || "resume"}.json`;
  const json = `${JSON.stringify({ resumes: [exportDocument] }, null, 2)}\n`;

  downloadBlob(
    new Blob([json], { type: "application/json;charset=utf-8" }),
    fileName,
  );
}
