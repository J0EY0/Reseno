import { apiRoutes, fetchApiResource, requestApi } from "@/lib/api-client";
import type {
  ExportResumePdfRequest,
  ExportResumePdfResponse,
} from "@/types/api";

export async function requestResumePdfExport(
  request: ExportResumePdfRequest,
) {
  return requestApi<ExportResumePdfResponse>(apiRoutes.resumePdfExport, {
    body: request,
    method: "POST",
  });
}

export async function downloadExportedPdf(result: ExportResumePdfResponse) {
  const response = await fetchApiResource(result.downloadUrl);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = result.fileName;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
