import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
} from "@/components/ai-elements/message";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type { AgentChatAttachment } from "@/types/api";
import { Check, Copy, Pencil, RotateCcw, X } from "lucide-react";

import { AgentMessageAttachments } from "./copilot-attachments";
import type { AgentPanelMessage } from "./copilot-message-model";

interface AgentUserMessageRowProps {
  copied: boolean;
  editedText: string;
  isEditing: boolean;
  isResponding: boolean;
  message: AgentPanelMessage;
  onCancelEdit: () => void;
  onCopy: () => void;
  onDownloadAttachment: (file: AgentChatAttachment) => void;
  onEditTextChange: (value: string) => void;
  onReferenceAttachment: (file: AgentChatAttachment) => void;
  onRetry: () => void;
  onStartEdit: () => void;
  onSubmitEdit: () => void;
  retryable: boolean;
  t: AppMessages;
}

/** Owns the user-message display/edit/retry state machine behind one row. */
export function AgentUserMessageRow({
  copied,
  editedText,
  isEditing,
  isResponding,
  message,
  onCancelEdit,
  onCopy,
  onDownloadAttachment,
  onEditTextChange,
  onReferenceAttachment,
  onRetry,
  onStartEdit,
  onSubmitEdit,
  retryable,
  t,
}: AgentUserMessageRowProps) {
  const submitDisabled = isResponding || !editedText.trim();
  const hasText = Boolean(message.text.trim());
  const executionStatus = message.execution?.status;
  const canRetry =
    retryable &&
    (executionStatus === "failed" || executionStatus === "cancelled");

  return (
    <Message from="user" className={cn(isEditing && "w-full !max-w-full")}>
      <div
        className={cn(
          "group/user-message flex max-w-full flex-col items-end",
          isEditing && "w-full",
        )}
      >
        {message.files?.length ? (
          <AgentMessageAttachments
            className={cn((isEditing || hasText) && "mb-1.5")}
            downloadLabel={t.agentAttachmentDownload}
            fallbackLabel={t.agentAttachmentFallback}
            files={message.files}
            onDownload={onDownloadAttachment}
            onReference={onReferenceAttachment}
            referenceLabel={t.agentAttachmentReference}
          />
        ) : null}

        {isEditing || hasText ? (
          <MessageContent
            className={cn(
              "ml-auto min-w-8 max-w-full self-end overflow-visible text-foreground",
              isEditing
                ? "!w-full !rounded-2xl border border-border/70 !bg-background !px-2.5 !py-1.5 shadow-[0_4px_18px_rgba(15,23,42,0.08)] transition-[border-color,box-shadow] focus-within:border-ring/35 focus-within:shadow-[0_8px_26px_rgba(15,23,42,0.10)]"
                : "w-fit !rounded-xl bg-secondary !px-3 !py-1 text-[15px] leading-5",
            )}
          >
            {isEditing ? (
              <div className="grid gap-1.5">
                <Textarea
                  autoFocus
                  value={editedText}
                  rows={1}
                  className="max-h-36 min-h-7 resize-none border-0 bg-transparent px-1 py-0 text-[15px] leading-6 shadow-none outline-none focus-visible:border-transparent focus-visible:ring-0"
                  onChange={(event) => onEditTextChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.preventDefault();
                      onCancelEdit();
                      return;
                    }

                    if (
                      event.key === "Enter" &&
                      (event.metaKey || event.ctrlKey)
                    ) {
                      event.preventDefault();
                      onSubmitEdit();
                    }
                  }}
                />
                <div className="flex items-center justify-end gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    className="h-6 rounded-md px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    onClick={onCancelEdit}
                  >
                    <X className="size-3" />
                    {t.agentCancelEdit}
                  </Button>
                  <Button
                    type="button"
                    size="xs"
                    className="h-6 rounded-md bg-foreground px-2.5 text-xs text-background shadow-none hover:bg-foreground/90"
                    disabled={submitDisabled}
                    onClick={onSubmitEdit}
                  >
                    <Check className="size-3" />
                    {t.agentSubmitEdit}
                  </Button>
                </div>
              </div>
            ) : (
              <span className="block whitespace-pre-wrap break-words leading-5 [overflow-wrap:anywhere]">
                {message.text}
              </span>
            )}
          </MessageContent>
        ) : null}

        {!isEditing && canRetry ? (
          <div className="mr-1 mt-1 flex items-center gap-1 text-xs text-muted-foreground">
            <span role="status">
              {executionStatus === "failed"
                ? t.agentRunFailed
                : t.agentRunCancelled}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="h-6 rounded-md px-1.5 text-xs hover:bg-muted hover:text-foreground"
              disabled={isResponding}
              onClick={onRetry}
            >
              <RotateCcw className="size-3" />
              {t.agentRetry}
            </Button>
          </div>
        ) : null}

        {!isEditing ? (
          <MessageActions className="pointer-events-none mr-1 mt-0.5 h-5 justify-end gap-1 opacity-0 transition-opacity duration-150 group-hover/user-message:pointer-events-auto group-hover/user-message:opacity-100 group-focus-within/user-message:pointer-events-auto group-focus-within/user-message:opacity-100">
            <MessageAction
              tooltip={copied ? t.agentCopiedMessage : t.agentCopyMessage}
              label={copied ? t.agentCopiedMessage : t.agentCopyMessage}
              variant="ghost"
              size="icon-xs"
              className="size-5 rounded-md text-muted-foreground transition-[background-color,box-shadow,color] hover:bg-muted hover:text-foreground hover:shadow-sm focus-visible:bg-muted focus-visible:text-foreground focus-visible:shadow-sm"
              onClick={onCopy}
            >
              {copied ? (
                <Check className="size-3" />
              ) : (
                <Copy className="size-3" />
              )}
            </MessageAction>
            <MessageAction
              tooltip={t.agentEditMessage}
              label={t.agentEditMessage}
              variant="ghost"
              size="icon-xs"
              className="size-5 rounded-md text-muted-foreground transition-[background-color,box-shadow,color] hover:bg-muted hover:text-foreground hover:shadow-sm focus-visible:bg-muted focus-visible:text-foreground focus-visible:shadow-sm"
              disabled={isResponding}
              onClick={onStartEdit}
            >
              <Pencil className="size-3" />
            </MessageAction>
          </MessageActions>
        ) : null}
      </div>
    </Message>
  );
}
