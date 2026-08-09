import type { PromptInputMessage } from "@/components/ai-elements/use-prompt-input-form";
import { deletePendingAgentAttachment } from "@/lib/agent-attachment-client";
import type { AgentChatAttachment } from "@/types/api";

export const MAX_AGENT_ATTACHMENT_BYTES = 10 * 1024 * 1024;
export const MAX_AGENT_ATTACHMENTS = 5;
export const TEXT_ATTACHMENT_ACCEPT = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/json",
  "application/xml",
  "text/plain",
  "text/csv",
  "text/markdown",
  ".md",
  ".markdown",
  ".yaml",
  ".yml",
].join(",");
export const IMAGE_ATTACHMENT_ACCEPT = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  TEXT_ATTACHMENT_ACCEPT,
].join(",");

interface PreparedAgentAttachment {
  body: FormData;
  byteLength: number;
}

export async function prepareAgentAttachment(
  file: PromptInputMessage["files"][number],
): Promise<PreparedAgentAttachment> {
  if (!file.url) {
    throw new Error("Attachment URL is unavailable.");
  }

  const response = await fetch(file.url);
  if (!response.ok) {
    throw new Error("Attachment data could not be read.");
  }

  const blob = await response.blob();
  const body = new FormData();
  body.append("file", blob, file.filename || "attachment");

  return {
    body,
    // Empty files still receive one unit of progress weight so a batch cannot
    // produce an invalid zero-byte denominator.
    byteLength: Math.max(blob.size, 1),
  };
}

export async function deletePendingUploads(
  resumeId: string,
  files: AgentChatAttachment[],
) {
  const attachmentIds = files
    .map((file) => file.id)
    .filter((id): id is string => Boolean(id));
  const results = await Promise.allSettled(
    attachmentIds.map((id) => deletePendingAgentAttachment(resumeId, id)),
  );

  // Cleanup is best-effort: the server may already have protected a file after
  // persisting a completed turn, in which case the pending-only delete rejects.
  if (results.some((result) => result.status === "rejected")) {
    console.warn("Some pending Agent attachments could not be removed.");
  }
}
