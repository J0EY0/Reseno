import { apiRoutes, uploadApi } from "@/lib/api-client";
import type { ImportResumeResponse, ImportTemplatesResponse } from "@/types/api";

export async function importResumePayload(file: File) {
  const body = new FormData();
  body.append("file", file);

  return uploadApi<ImportResumeResponse>(apiRoutes.resumeImport, body);
}

export async function importTemplatePayload(file: File) {
  const body = new FormData();
  body.append("file", file);

  return uploadApi<ImportTemplatesResponse>(apiRoutes.templateImport, body);
}
