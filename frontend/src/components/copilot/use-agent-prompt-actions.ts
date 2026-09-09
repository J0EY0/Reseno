import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/use-prompt-input-form";
import type { AppMessages } from "@/i18n";
import { uploadAgentAttachment } from "@/lib/agent-attachment-client";
import { isAbortError } from "@/lib/api-client";
import { notifyApiError } from "@/lib/api-error-notifier";
import type { AgentChatAttachment } from "@/types/api";

import {
  MAX_AGENT_ATTACHMENTS,
  deletePendingUploads,
  prepareAgentAttachment,
} from "./copilot-attachment-policy";
import type { SendAgentPrompt } from "./copilot-panel-types";

export function useAgentPromptActions({
  hasConfiguredModel,
  isRequestBusy,
  isSessionReady,
  resumeId,
  sessionResetVersion,
  sendPrompt,
  stopConversation,
  t,
}: {
  hasConfiguredModel: boolean;
  isRequestBusy: boolean;
  isSessionReady: boolean;
  resumeId?: string;
  sessionResetVersion: number;
  sendPrompt: SendAgentPrompt;
  stopConversation: () => void;
  t: AppMessages;
}) {
  const [isSubmittingPrompt, setIsSubmittingPrompt] = useState(false);
  const [attachmentUploadProgress, setAttachmentUploadProgress] = useState<
    number | null
  >(null);
  const [promptLocalAttachmentCount, setPromptLocalAttachmentCount] =
    useState(0);
  const [referencedAttachments, setReferencedAttachments] = useState<
    AgentChatAttachment[]
  >([]);
  const promptSubmissionRef = useRef(false);
  const referencedAttachmentsRef = useRef<AgentChatAttachment[]>([]);
  const activeUploadAbortRef = useRef<AbortController | null>(null);
  const currentResumeIdRef = useRef(resumeId);
  currentResumeIdRef.current = resumeId;

  useEffect(() => {
    referencedAttachmentsRef.current = [];
    setReferencedAttachments([]);
    setPromptLocalAttachmentCount(0);
  }, [resumeId, sessionResetVersion]);

  useEffect(() => {
    return () => activeUploadAbortRef.current?.abort();
  }, []);

  const referenceHistoryAttachment = useCallback(
    (file: AgentChatAttachment) => {
      if (!file.id) {
        return;
      }

      const current = referencedAttachmentsRef.current;
      if (current.some((attachment) => attachment.id === file.id)) {
        return;
      }
      if (
        current.length + promptLocalAttachmentCount >=
        MAX_AGENT_ATTACHMENTS
      ) {
        toast.info(t.agentAttachmentLimitReached, {
          closeButton: true,
        });
        return;
      }

      const next = [...current, file];
      referencedAttachmentsRef.current = next;
      setReferencedAttachments(next);
    },
    [promptLocalAttachmentCount, t.agentAttachmentLimitReached],
  );

  const removeReferencedAttachment = useCallback((attachmentId: string) => {
    const next = referencedAttachmentsRef.current.filter(
      (attachment) => attachment.id !== attachmentId,
    );
    referencedAttachmentsRef.current = next;
    setReferencedAttachments(next);
  }, []);

  const submitPrompt = useCallback(
    async (message: PromptInputMessage) => {
      if (isSubmittingPrompt || promptSubmissionRef.current || isRequestBusy) {
        throw new Error("An Agent prompt submission is already in progress.");
      }

      if (!hasConfiguredModel) {
        toast.info(t.agentModelRequiredHint, {
          closeButton: true,
        });
        throw new Error("An Agent model must be configured before sending.");
      }

      if (!isSessionReady) {
        throw new Error("The Agent session is not ready for a new prompt.");
      }

      const referencedSnapshot = referencedAttachmentsRef.current.map(
        (attachment) => ({ ...attachment }),
      );

      if (
        message.files.length + referencedSnapshot.length >
        MAX_AGENT_ATTACHMENTS
      ) {
        toast.info(t.agentAttachmentLimitReached, {
          closeButton: true,
        });
        throw new Error("The Agent attachment limit was exceeded.");
      }

      if (message.files.length > 0 && !resumeId) {
        toast.error(t.agentAttachmentUploadFailed, {
          closeButton: true,
        });
        throw new Error("A resume session is required to upload attachments.");
      }

      promptSubmissionRef.current = true;
      setIsSubmittingPrompt(true);
      const uploadedFiles: AgentChatAttachment[] = [];
      const uploadAbortController = new AbortController();
      activeUploadAbortRef.current?.abort();
      activeUploadAbortRef.current = uploadAbortController;
      let sendStarted = false;
      let requestAccepted = false;

      try {
        if (resumeId) {
          const preparedFiles = await Promise.all(
            message.files.map(prepareAgentAttachment),
          );
          const totalBytes = preparedFiles.reduce(
            (sum, file) => sum + file.byteLength,
            0,
          );
          let completedBytes = 0;

          if (preparedFiles.length > 0) {
            setAttachmentUploadProgress(0);
          }

          // Upload sequentially so a later failure can remove every earlier
          // pending upload instead of leaving an orphaned partial batch.
          for (const file of preparedFiles) {
            const uploadedFile = await uploadAgentAttachment(
              file.body,
              resumeId,
              {
                onProgress: ({ loaded, total }) => {
                  const fileRatio =
                    total && total > 0
                      ? Math.min(loaded / total, 1)
                      : Math.min(loaded / file.byteLength, 1);
                  const uploadedBytes =
                    completedBytes + file.byteLength * fileRatio;

                  // Keep 100% for the point where the server has accepted the
                  // full batch, rather than during response latency.
                  setAttachmentUploadProgress(
                    Math.min(
                      99,
                      Math.round((uploadedBytes / totalBytes) * 100),
                    ),
                  );
                },
                signal: uploadAbortController.signal,
              },
            );
            uploadedFiles.push(uploadedFile);
            completedBytes += file.byteLength;
            setAttachmentUploadProgress(
              Math.round((completedBytes / totalBytes) * 100),
            );
          }
        }

        if (resumeId !== currentResumeIdRef.current) {
          throw new Error(
            "The active resume changed while uploading attachments.",
          );
        }

        const currentReferencedIds = new Set(
          referencedAttachmentsRef.current.map((attachment) => attachment.id),
        );
        const activeReferencedAttachments = referencedSnapshot.filter(
          (attachment) =>
            Boolean(attachment.id && currentReferencedIds.has(attachment.id)),
        );
        if (activeUploadAbortRef.current === uploadAbortController) {
          activeUploadAbortRef.current = null;
        }
        sendStarted = true;
        const sendOperation = sendPrompt(message.text, [
          ...activeReferencedAttachments,
          ...uploadedFiles,
        ]);
        if (!sendOperation.submitted) {
          await sendOperation.completion;
          throw new Error("The Agent request was not submitted.");
        }
        setIsSubmittingPrompt(false);
        setAttachmentUploadProgress(null);
        requestAccepted = await sendOperation.accepted;
        if (!requestAccepted) {
          await sendOperation.completion;
          throw new Error("The Agent request was not accepted by the server.");
        }

        const submittedReferenceIds = new Set(
          activeReferencedAttachments.map((attachment) => attachment.id),
        );
        const remainingReferencedAttachments =
          referencedAttachmentsRef.current.filter(
            (attachment) => !submittedReferenceIds.has(attachment.id),
          );
        referencedAttachmentsRef.current = remainingReferencedAttachments;
        setReferencedAttachments(remainingReferencedAttachments);

        void (async () => {
          const status = await sendOperation.completion;
          if (status !== "completed" && resumeId && uploadedFiles.length > 0) {
            await deletePendingUploads(resumeId, uploadedFiles);
          }
        })()
          .catch(async (error) => {
            if (resumeId && uploadedFiles.length > 0) {
              await deletePendingUploads(resumeId, uploadedFiles);
            }
            console.error(
              "Failed to finish the Agent prompt submission.",
              error,
            );
          })
          .finally(() => {
            promptSubmissionRef.current = false;
          });
      } catch (error) {
        if (resumeId && uploadedFiles.length > 0) {
          await deletePendingUploads(resumeId, uploadedFiles);
        }

        if (!isAbortError(error)) {
          console.error(
            sendStarted
              ? "Failed to start the Agent request."
              : "Failed to upload agent attachment.",
            error,
          );
        }
        if (!sendStarted && !isAbortError(error)) {
          notifyApiError(error, t.agentAttachmentUploadFailed);
        }
        throw error;
      } finally {
        setIsSubmittingPrompt(false);
        setAttachmentUploadProgress(null);
        if (activeUploadAbortRef.current === uploadAbortController) {
          activeUploadAbortRef.current = null;
        }
        if (!requestAccepted) {
          promptSubmissionRef.current = false;
        }
      }
    },
    [
      hasConfiguredModel,
      isRequestBusy,
      isSubmittingPrompt,
      isSessionReady,
      resumeId,
      sendPrompt,
      t.agentAttachmentLimitReached,
      t.agentAttachmentUploadFailed,
      t.agentModelRequiredHint,
    ],
  );

  const stopResponding = useCallback(() => {
    if (isSubmittingPrompt && activeUploadAbortRef.current) {
      activeUploadAbortRef.current.abort();
      return;
    }

    stopConversation();
  }, [isSubmittingPrompt, stopConversation]);

  return {
    attachmentUploadProgress,
    isSubmittingPrompt,
    promptAttachmentCapacity: Math.max(
      0,
      MAX_AGENT_ATTACHMENTS - referencedAttachments.length,
    ),
    referenceHistoryAttachment,
    referencedAttachments,
    removeReferencedAttachment,
    setPromptLocalAttachmentCount,
    stopResponding,
    submitPrompt,
  };
}

export type AgentPromptActions = ReturnType<typeof useAgentPromptActions>;
