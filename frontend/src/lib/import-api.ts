import { apiRoutes, uploadApi } from "@/lib/api-client";
import type {
  ApiRequestOptions,
  ImportResumeResponse,
  ImportTemplatesResponse,
} from "@/types/api";

export async function importResumePayload(
  file: File,
  options: Pick<ApiRequestOptions, "signal" | "notifyOnError"> = {},
) {
  const body = new FormData();
  body.append("file", file);

  return uploadApi<ImportResumeResponse>(apiRoutes.resumeImport, body, options);
}

export async function importTemplatePayload(file: File) {
  const body = new FormData();
  body.append("file", file);

  return uploadApi<ImportTemplatesResponse>(apiRoutes.templateImport, body);
}
