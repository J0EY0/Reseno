import {
  Attachment,
  AttachmentHoverCard,
  AttachmentHoverCardContent,
  AttachmentHoverCardTrigger,
  AttachmentInfo,
  AttachmentPreview,
  AttachmentRemove,
  Attachments,
  type AttachmentData,
  getAttachmentLabel,
  getMediaCategory,
} from "@/components/ai-elements/attachments";
import {
  PromptInputButton,
  PromptInputSubmit,
} from "@/components/ai-elements/prompt-input";
import {
  usePromptInputAttachments,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input-context";
import { Button } from "@/components/ui/button";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type { AgentChatAttachment } from "@/types/api";
import { ArrowUp, Download, Plus } from "lucide-react";
import { useEffect } from "react";

import type { AgentRequestPhase } from "./agent-conversation-runtime";

function toAttachmentData(
  file: AgentChatAttachment,
  index: number,
  fallbackLabel: string,
): AttachmentData {
  // Persisted messages intentionally contain only an opaque attachment id and
  // metadata. Keeping the URL empty makes AI Elements render a safe file icon
  // instead of relying on an expired browser-local Blob URL.
  return {
    filename: file.filename || fallbackLabel,
    id:
      file.id ||
      `agent-attachment-${index}-${file.filename || fallbackLabel}`,
    mediaType:
      file.mediaType ||
      (file.kind === "image" ? "image/*" : "application/octet-stream"),
    type: "file",
    url: "",
  };
}

export function AgentMessageAttachments({
  className,
  downloadLabel,
  fallbackLabel,
  files,
  onDownload,
  onReference,
  referenceLabel,
}: {
  className?: string;
  downloadLabel: string;
  fallbackLabel: string;
  files: AgentChatAttachment[];
  onDownload: (file: AgentChatAttachment) => void;
  onReference: (file: AgentChatAttachment) => void;
  referenceLabel: string;
}) {
  return (
    <Attachments
      className={cn("max-w-full justify-end", className)}
      variant="grid"
    >
      {files.map((file, index) => {
        const attachment = toAttachmentData(file, index, fallbackLabel);
        const canOpen = Boolean(file.id);

        return (
          <AttachmentHoverCard
            closeDelay={100}
            key={attachment.id}
            openDelay={300}
          >
            <AttachmentHoverCardTrigger asChild>
              <Attachment
                aria-label={attachment.filename || fallbackLabel}
                className={cn(
                  "max-w-full border border-border/70 bg-background hover:bg-background",
                  canOpen ? "cursor-pointer" : "cursor-default",
                )}
                data={attachment}
                onClick={() => {
                  if (canOpen) {
                    onDownload(file);
                  }
                }}
                onKeyDown={(event) => {
                  if (
                    canOpen &&
                    (event.key === "Enter" || event.key === " ")
                  ) {
                    event.preventDefault();
                    onDownload(file);
                  }
                }}
                role={canOpen ? "button" : undefined}
                tabIndex={canOpen ? 0 : undefined}
              >
                <AttachmentPreview className="pb-7 [&_svg]:size-5" />
                <span className="absolute inset-x-0 bottom-0 block truncate border-t border-border/60 bg-background/95 px-2 py-1.5 text-[11px] leading-4 text-foreground">
                  {attachment.filename || fallbackLabel}
                </span>
              </Attachment>
            </AttachmentHoverCardTrigger>
            <AttachmentHoverCardContent side="top" sideOffset={8}>
              <div className="grid max-w-72 gap-2">
                <p className="break-words px-1 text-sm font-medium leading-5">
                  {attachment.filename || fallbackLabel}
                </p>
                {canOpen ? (
                  <div className="flex items-center gap-1">
                    <Button
                      className="h-7 px-2 text-xs"
                      onClick={() => onDownload(file)}
                      size="xs"
                      type="button"
                      variant="ghost"
                    >
                      <Download className="size-3.5" />
                      {downloadLabel}
                    </Button>
                    <Button
                      className="h-7 px-2 text-xs"
                      onClick={() => onReference(file)}
                      size="xs"
                      type="button"
                      variant="ghost"
                    >
                      <Plus className="size-3.5" />
                      {referenceLabel}
                    </Button>
                  </div>
                ) : null}
              </div>
            </AttachmentHoverCardContent>
          </AttachmentHoverCard>
        );
      })}
    </Attachments>
  );
}

function AgentPromptAttachment({
  attachment,
  onRemove,
  removeLabel,
}: {
  attachment: AttachmentData;
  onRemove?: () => void;
  removeLabel: string;
}) {
  const label = getAttachmentLabel(attachment);
  const mediaCategory = getMediaCategory(attachment);

  return (
    <AttachmentHoverCard closeDelay={100} openDelay={300}>
      <AttachmentHoverCardTrigger asChild>
        <Attachment
          className="w-fit min-w-0 max-w-[13rem] overflow-hidden"
          data={attachment}
          onRemove={onRemove}
        >
          <div className="relative size-5 shrink-0">
            <div
              className={cn(
                "absolute inset-0",
                onRemove && "transition-opacity group-hover:opacity-0",
              )}
            >
              <AttachmentPreview />
            </div>
            {onRemove ? (
              <AttachmentRemove className="absolute inset-0" label={removeLabel} />
            ) : null}
          </div>
          <AttachmentInfo />
        </Attachment>
      </AttachmentHoverCardTrigger>
      <AttachmentHoverCardContent side="top" sideOffset={8}>
        <div className="space-y-3">
          {mediaCategory === "image" &&
            attachment.type === "file" &&
            attachment.url && (
              <div className="flex max-h-64 w-64 items-center justify-center overflow-hidden rounded-md border">
                <img
                  alt={label}
                  className="max-h-full max-w-full object-contain"
                  height={256}
                  src={attachment.url}
                  width={256}
                />
              </div>
            )}
          <div className="max-w-72 px-0.5">
            <p className="break-words font-medium text-sm leading-5">{label}</p>
          </div>
        </div>
      </AttachmentHoverCardContent>
    </AttachmentHoverCard>
  );
}

export function AgentPromptAttachmentsDisplay({
  disableRemoval,
  fallbackLabel,
  removeLabel,
  onLocalCountChange,
  onRemoveReferenced,
  referencedFiles,
}: {
  disableRemoval: boolean;
  fallbackLabel: string;
  removeLabel: string;
  onLocalCountChange: (count: number) => void;
  onRemoveReferenced: (id: string) => void;
  referencedFiles: AgentChatAttachment[];
}) {
  const attachments = usePromptInputAttachments();

  useEffect(() => {
    onLocalCountChange(attachments.files.length);
  }, [attachments.files.length, onLocalCountChange]);

  if (attachments.files.length === 0 && referencedFiles.length === 0) {
    return null;
  }

  return (
    <Attachments
      className="w-full min-w-0 justify-start self-start px-4 pt-3"
      variant="inline"
    >
      {attachments.files.map((attachment) => (
        <AgentPromptAttachment
          attachment={attachment}
          key={`local-${attachment.id}`}
          removeLabel={removeLabel}
          onRemove={
            disableRemoval
              ? undefined
              : () => attachments.remove(attachment.id)
          }
        />
      ))}
      {referencedFiles.map((file, index) => {
        const attachment = toAttachmentData(file, index, fallbackLabel);

        return (
          <AgentPromptAttachment
            attachment={attachment}
            key={`referenced-${attachment.id}`}
            removeLabel={removeLabel}
            onRemove={
              disableRemoval
                ? undefined
                : () => {
                    if (file.id) {
                      onRemoveReferenced(file.id);
                    }
                  }
            }
          />
        );
      })}
    </Attachments>
  );
}

export function AgentPromptAttachmentButton({
  disabled,
  label,
}: {
  disabled: boolean;
  label: string;
}) {
  const attachments = usePromptInputAttachments();

  return (
    <PromptInputButton
      aria-label={label}
      className="text-foreground disabled:cursor-not-allowed"
      disabled={disabled}
      onClick={() => attachments.openFileDialog()}
      tooltip={label}
    >
      <Plus className="size-4" />
    </PromptInputButton>
  );
}

export function AgentPromptSubmitButton({
  attachmentUploadProgress,
  hasConfiguredModel,
  hasReferencedAttachments,
  isSessionReady,
  isSubmittingPrompt,
  onStop,
  requestPhase,
  t,
}: {
  attachmentUploadProgress: number | null;
  hasConfiguredModel: boolean;
  hasReferencedAttachments: boolean;
  isSessionReady: boolean;
  isSubmittingPrompt: boolean;
  onStop: () => void;
  requestPhase: AgentRequestPhase;
  t: AppMessages;
}) {
  const controller = usePromptInputController();
  const attachments = usePromptInputAttachments();
  const hasPromptContent =
    controller.textInput.value.trim().length > 0 ||
    attachments.files.length > 0 ||
    hasReferencedAttachments;
  const isRequestBusy = requestPhase !== "idle";
  const isDisabled =
    !isRequestBusy &&
    !isSubmittingPrompt &&
    (!hasConfiguredModel || !isSessionReady || !hasPromptContent);

  return (
    <PromptInputSubmit
      aria-label={
        attachmentUploadProgress !== null
          ? t.agentAttachmentUploading.replace(
              "{progress}",
              String(attachmentUploadProgress),
            )
          : isRequestBusy
            ? t.agentStopResponse
            : t.agentSendPrompt
      }
      status={
        isSubmittingPrompt || requestPhase === "preparing"
          ? "submitted"
          : requestPhase === "responding"
            ? "streaming"
            : "ready"
      }
      disabled={isDisabled}
      onStop={onStop}
      className="ml-3 size-8 min-w-8 shrink-0 rounded-full bg-foreground p-0 text-background shadow-none transition-none hover:!bg-foreground hover:!text-background disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100 disabled:cursor-not-allowed"
    >
      {attachmentUploadProgress !== null ? (
        <span
          aria-hidden="true"
          className="text-[10px] font-semibold tabular-nums"
        >
          {attachmentUploadProgress}%
        </span>
      ) : requestPhase === "responding" ? (
        <span
          aria-hidden="true"
          className="size-2.5 rounded-[3px] bg-current"
        />
      ) : isSubmittingPrompt || requestPhase === "preparing" ? null : (
        <ArrowUp aria-hidden="true" className="size-4" />
      )}
    </PromptInputSubmit>
  );
}
