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
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorLogo,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputProvider,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Shimmer } from "@/components/ai-elements/shimmer";
import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationCardTrigger,
  InlineCitationCarousel,
  InlineCitationCarouselContent,
  InlineCitationCarouselHeader,
  InlineCitationCarouselIndex,
  InlineCitationCarouselItem,
  InlineCitationCarouselNext,
  InlineCitationCarouselPrev,
  InlineCitationSource,
  InlineCitationText,
} from "@/components/ai-elements/inline-citation";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Textarea } from "@/components/ui/textarea";
import {
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Copy,
  Download,
  Pencil,
  Plus,
  RotateCcw,
  SquareTerminal,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import type { StickToBottomContext } from "use-stick-to-bottom";

import { getMessagesSync, locales, type AppMessages, type Locale } from "@/i18n";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  connectAgentRun,
  deletePendingAgentAttachment,
  downloadAgentAttachment,
  loadActiveAgentRun,
  loadAgentSession,
  replaceAgentSession,
  sendAgentChatMessage,
  stopAgentRun,
  type AgentChatStreamOptions,
  uploadAgentAttachment,
} from "@/lib/agent-api";
import {
  getAgentQualityWarningCount,
  mergeStreamingAgentMessage,
  shouldRollbackOptimisticAgentMessages,
  shouldShowAgentDraftActions,
} from "@/lib/agent-panel-state";
import {
  isAbortError,
  isApiErrorCode,
  isApiErrorToastShown,
} from "@/lib/api-client";
import {
  getAgentToolLabelKey,
  getVisibleCompletedTools,
  getVisibleToolIds,
  isAgentEditExecutionTool,
  isToolFailure,
  isToolRunning,
} from "@/lib/agent-tool-display";
import { isPlainAgentText } from "@/lib/agent-message-rendering";
import languagePatterns from "@/lib/language-patterns.json";
import { createId, getKeywordMatch } from "@/lib/resume";
import { cn } from "@/lib/utils";
import type {
  AgentChatAttachment,
  AgentChatMessage,
  AgentChatResponse,
  AgentConversationMessage,
  AgentDraftState,
  AgentResumeEditSuggestion,
  AgentRunResponse,
  AgentRunStatus,
  AgentSessionResponse,
  AgentSource,
  AgentStoredMessage,
  AgentTimelinePart,
  AgentTurnExecution,
  AgentToolInvocation,
  AgentTransactionState,
} from "@/types/api";
import type {
  KeywordMatch,
  ModelConfig,
  ResumeData,
} from "@/types/resume";

const AGENT_REQUEST_DEBOUNCE_MS = 420;
const MAX_AGENT_ATTACHMENT_BYTES = 10 * 1024 * 1024;
const MAX_AGENT_ATTACHMENTS = 5;
const TEXT_ATTACHMENT_ACCEPT = [
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
const IMAGE_ATTACHMENT_ACCEPT = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  TEXT_ATTACHMENT_ACCEPT,
].join(",");
const JOB_BRIEF_PROMPT_PATTERN = new RegExp(
  languagePatterns.jobBriefPrompt.map(escapeRegExp).join("|"),
  "i",
);
const JOB_BRIEF_CONTEXT_PATTERN = new RegExp(
  languagePatterns.jobBriefContext.map(escapeRegExp).join("|"),
  "i",
);
const ALL_AGENT_TRANSIENT_MODEL_STATUS_TEXTS = locales.flatMap(
  (locale) => getMessagesSync(locale).agentTransientModelStatusTexts,
);
const AGENT_MARKDOWN_CLASSNAME =
  "[&_h1]:!mb-2 [&_h1]:!mt-3 [&_h1]:!text-base [&_h1]:!font-semibold [&_h1]:!leading-7 [&_h1]:!tracking-normal [&_h2]:!mb-2 [&_h2]:!mt-3 [&_h2]:!text-base [&_h2]:!font-semibold [&_h2]:!leading-7 [&_h2]:!tracking-normal [&_h3]:!mb-1.5 [&_h3]:!mt-2.5 [&_h3]:!text-sm [&_h3]:!font-semibold [&_h3]:!leading-6";

interface AgentPanelMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  files?: AgentChatAttachment[];
  response?: AgentChatMessage;
  execution?: AgentTurnExecution;
}

interface PendingAgentSend {
  optimisticMessageId: string;
  resolve: (status: AgentRunStatus) => void;
  resumeId?: string;
  rollbackMessages: AgentPanelMessage[];
}

function isPendingSendOwner(
  currentOwnerId: string | null,
  pendingOwnerId: string | undefined,
  pendingResumeId: string | undefined,
  currentResumeId: string | undefined,
) {
  return (
    currentOwnerId !== null &&
    currentOwnerId === pendingOwnerId &&
    pendingResumeId === currentResumeId
  );
}

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

function AgentMessageAttachments({
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
          <AttachmentHoverCard closeDelay={100} key={attachment.id} openDelay={300}>
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

function getModelProvider(config: ModelConfig) {
  return {
    id: config.iconProvider || config.provider,
    label: config.providerLabel || config.provider,
  };
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getModelDisplayName(config: ModelConfig) {
  return config.nickname.trim() || config.model;
}

function getModelTriggerName(config: ModelConfig) {
  const raw = config.model.trim();

  if (!raw) {
    return "";
  }

  if (raw.toLowerCase().startsWith("claude-")) {
    return raw.replace(/^claude-/i, "").toUpperCase();
  }

  return raw.toUpperCase();
}

function getModelSecondaryName(config: ModelConfig) {
  const nickname = config.nickname.trim();

  if (!nickname || nickname === config.model) {
    return null;
  }

  return config.model;
}

function AgentPromptAttachment({
  attachment,
  onRemove,
}: {
  attachment: AttachmentData;
  onRemove: () => void;
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
            <div className="absolute inset-0 transition-opacity group-hover:opacity-0">
              <AttachmentPreview />
            </div>
            <AttachmentRemove className="absolute inset-0" />
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

function AgentPromptAttachmentsDisplay({
  fallbackLabel,
  onLocalCountChange,
  onRemoveReferenced,
  referencedFiles,
}: {
  fallbackLabel: string;
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
          onRemove={() => attachments.remove(attachment.id)}
        />
      ))}
      {referencedFiles.map((file, index) => {
        const attachment = toAttachmentData(file, index, fallbackLabel);

        return (
          <AgentPromptAttachment
            attachment={attachment}
            key={`referenced-${attachment.id}`}
            onRemove={() => {
              if (file.id) {
                onRemoveReferenced(file.id);
              }
            }}
          />
        );
      })}
    </Attachments>
  );
}

function AgentPromptAttachmentButton({
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

function AgentPromptSubmitButton({
  attachmentUploadProgress,
  hasConfiguredModel,
  hasReferencedAttachments,
  isResponding,
  isSubmittingPrompt,
  onStop,
  t,
}: {
  attachmentUploadProgress: number | null;
  hasConfiguredModel: boolean;
  hasReferencedAttachments: boolean;
  isResponding: boolean;
  isSubmittingPrompt: boolean;
  onStop: () => void;
  t: AppMessages;
}) {
  const controller = usePromptInputController();
  const attachments = usePromptInputAttachments();
  const hasPromptContent =
    controller.textInput.value.trim().length > 0 ||
    attachments.files.length > 0 ||
    hasReferencedAttachments;
  const isDisabled =
    !hasConfiguredModel ||
    (!isResponding && !isSubmittingPrompt && !hasPromptContent);

  return (
    <PromptInputSubmit
      aria-label={
        attachmentUploadProgress !== null
          ? t.agentAttachmentUploading.replace(
              "{progress}",
              String(attachmentUploadProgress),
            )
          : isResponding
            ? t.agentStopResponse
            : t.agentSendPrompt
      }
      status={
        isSubmittingPrompt
          ? "submitted"
          : isResponding
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
      ) : isResponding ? (
        <span
          aria-hidden="true"
          className="size-2.5 rounded-[3px] bg-current"
        />
      ) : isSubmittingPrompt ? null : (
        <ArrowUp aria-hidden="true" className="size-4" />
      )}
    </PromptInputSubmit>
  );
}

function isLikelyJobBriefPrompt(prompt: string) {
  const trimmed = prompt.trim();
  const hasStructuredBody =
    trimmed.length >= 140 ||
    trimmed.split(/\n+/).filter(Boolean).length >= 3;

  // Length alone cannot distinguish a JD from admission or scholarship rules.
  return (
    JOB_BRIEF_CONTEXT_PATTERN.test(trimmed) &&
    (hasStructuredBody || JOB_BRIEF_PROMPT_PATTERN.test(trimmed))
  );
}

interface PreparedAgentAttachment {
  body: FormData;
  byteLength: number;
}

async function prepareAgentAttachment(
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

async function deletePendingUploads(
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

function toConversationMessage(
  message: AgentPanelMessage,
): AgentConversationMessage {
  return {
    files: message.files,
    id: message.id,
    response:
      message.role === "assistant" && message.response
        ? toConversationResponse(message.response)
        : undefined,
    role: message.role,
    text: message.text,
  };
}

function toConversationResponse(
  response: AgentChatMessage,
): AgentConversationMessage["response"] {
  return {
    actions: response.actions,
    edits: response.edits?.map((edit) => ({
      evidenceRefs: edit.evidenceRefs,
      id: edit.id,
      operation: edit.operation,
      reason: edit.reason,
      replacement: edit.replacement,
      status: edit.status,
      target: edit.target,
      title: edit.title,
    })),
    finishMissing: response.finishMissing,
    id: response.id,
    role: "assistant",
    sources: response.sources?.map((source) => ({
      id: source.id,
      sourceType: source.sourceType,
      title: source.title,
      url: source.url,
    })),
    text: response.text,
    timeline: response.timeline,
    transactionState: response.transactionState,
    tools: response.tools?.map((tool) => ({
      id: tool.id,
      state: tool.state,
      title: tool.title,
      type: tool.type,
    })),
  };
}

function isCitationSource(source: AgentSource) {
  if (source.id === "source-jd-search-query") {
    return false;
  }

  if (source.sourceType === "web" && !source.url) {
    return false;
  }

  return (
    source.sourceType === "web" ||
    source.sourceType === "jobBrief" ||
    source.sourceType === "attachment"
  );
}

function stripTransientModelStatus(
  text: string,
  transientStatusTexts: readonly string[],
) {
  const trimmed = text.trim();

  return transientStatusTexts.some((statusText) => statusText.trim() === trimmed)
    ? ""
    : text;
}

function sanitizeAgentResponse(
  message: AgentChatMessage,
  transientStatusTexts: readonly string[],
): AgentChatMessage {
  return {
    ...message,
    text: stripTransientModelStatus(message.text, transientStatusTexts),
    updates: [],
    sources: message.sources?.filter(isCitationSource),
  };
}

function toAssistantPanelMessage(
  message: AgentChatMessage,
  transientStatusTexts: readonly string[],
): AgentPanelMessage {
  const response = sanitizeAgentResponse(message, transientStatusTexts);

  return {
    id: message.id,
    role: "assistant",
    text: response.text,
    response,
  };
}

function getValidSourceUrl(source: AgentSource) {
  if (!source.url) {
    return null;
  }

  try {
    return new URL(source.url).toString();
  } catch {
    return null;
  }
}

function splitTrailingCitationText(text: string) {
  const trimmedText = text.trimEnd();
  const trailingWhitespace = text.slice(trimmedText.length);

  if (!trimmedText) {
    return { citationText: "", prefix: "", trailingWhitespace };
  }

  const boundaryMatch = /[。！？.!?\n](?![\s\S]*[。！？.!?\n])/.exec(
    trimmedText.slice(0, -1),
  );
  const cutIndex = boundaryMatch ? boundaryMatch.index + 1 : -1;
  const citationText =
    cutIndex >= 0 ? trimmedText.slice(cutIndex).trimStart() : trimmedText;

  if (citationText.length < 8) {
    return { citationText: trimmedText, prefix: "", trailingWhitespace };
  }

  return {
    citationText,
    prefix: cutIndex >= 0 ? trimmedText.slice(0, cutIndex) : "",
    trailingWhitespace,
  };
}

function AgentInlineCitationCard({
  sources,
}: {
  sources: AgentSource[] | undefined;
}) {
  const citationSources = sources
    ?.map((source) => {
      const url = getValidSourceUrl(source);

      return url ? { ...source, url } : null;
    })
    .filter((source): source is AgentSource & { url: string } =>
      Boolean(source),
    );

  if (!citationSources?.length) {
    return null;
  }

  const triggerSources = citationSources.map((source) => source.url);

  return (
    <InlineCitationCard>
      <InlineCitationCardTrigger sources={triggerSources} />
      <InlineCitationCardBody>
        <InlineCitationCarousel>
          <InlineCitationCarouselHeader>
            <InlineCitationCarouselPrev />
            <InlineCitationCarouselNext />
            <InlineCitationCarouselIndex />
          </InlineCitationCarouselHeader>
          <InlineCitationCarouselContent>
            {citationSources.map((source) => (
              <InlineCitationCarouselItem key={source.id}>
                <InlineCitationSource title={source.title} url={source.url} />
              </InlineCitationCarouselItem>
            ))}
          </InlineCitationCarouselContent>
        </InlineCitationCarousel>
      </InlineCitationCardBody>
    </InlineCitationCard>
  );
}

function AgentAssistantResponse({
  removeMarkdownTables,
  sources,
  text,
}: {
  removeMarkdownTables?: boolean;
  sources: AgentSource[] | undefined;
  text: string;
}) {
  const responseText = removeMarkdownTables
    ? removeMarkdownTableBlocks(text)
    : text;

  if (!responseText.trim()) {
    return null;
  }

  if (!sources?.some((source) => getValidSourceUrl(source))) {
    return (
      <MessageResponse className={AGENT_MARKDOWN_CLASSNAME}>
        {responseText}
      </MessageResponse>
    );
  }

  if (!isPlainAgentText(responseText)) {
    return (
      <>
        <MessageResponse className={AGENT_MARKDOWN_CLASSNAME}>
          {responseText}
        </MessageResponse>
        <span className="mt-1 inline-block text-sm leading-relaxed">
          <InlineCitation>
            <AgentInlineCitationCard sources={sources} />
          </InlineCitation>
        </span>
      </>
    );
  }

  const { citationText, prefix, trailingWhitespace } =
    splitTrailingCitationText(responseText);

  return (
    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
      {prefix}
      {prefix && !/\s$/.test(prefix) ? " " : null}
      <InlineCitation>
        <InlineCitationText>{citationText}</InlineCitationText>
        <AgentInlineCitationCard sources={sources} />
      </InlineCitation>
      {trailingWhitespace}
    </p>
  );
}

function removeMarkdownTableBlocks(text: string) {
  const tableRowPattern = /^\s*\|.*\|\s*$/;
  const tableSeparatorPattern =
    /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
  const lines = text.split(/\r?\n/);
  const keptLines: string[] = [];
  let removedTableLine = false;

  for (const line of lines) {
    const isMarkdownTableLine =
      tableRowPattern.test(line) || tableSeparatorPattern.test(line);

    if (isMarkdownTableLine) {
      removedTableLine = true;
      continue;
    }

    if (removedTableLine && !line.trim()) {
      removedTableLine = false;
      continue;
    }

    removedTableLine = false;
    keptLines.push(line);
  }

  return keptLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function toPanelMessage(
  message: AgentStoredMessage,
  transientStatusTexts: readonly string[],
): AgentPanelMessage {
  const messageId = message.id ?? createId("agent-stored");
  const text = stripTransientModelStatus(message.text, transientStatusTexts);
  const fallbackResponse: AgentChatMessage | undefined =
    message.role === "assistant"
      ? {
          id: messageId,
          role: "assistant",
          text,
        }
      : undefined;

  return {
    files: message.files,
    id: messageId,
    role: message.role,
    text,
    response: message.response
      ? sanitizeAgentResponse(message.response, transientStatusTexts)
      : fallbackResponse,
  };
}

function toPanelMessages(
  session: AgentSessionResponse,
  transientStatusTexts: readonly string[],
) {
  const latestExecutionByTurn = new Map<string, AgentTurnExecution>();
  for (const execution of session.executions) {
    latestExecutionByTurn.set(execution.turnId, execution);
  }

  return session.messages.map((message) => ({
    ...toPanelMessage(message, transientStatusTexts),
    execution:
      message.role === "user"
        ? latestExecutionByTurn.get(message.id)
        : undefined,
  }));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function hasAssistantRenderableContent(message: AgentPanelMessage) {
  const response = message.response;

  return Boolean(
    message.text.trim() ||
      response?.timeline?.some(
        (part) => part.text?.trim() || part.toolIds?.length,
      ) ||
      response?.tools?.length ||
      response?.edits?.length ||
      response?.sources?.length,
  );
}

function getToolActivityLabel(tool: AgentToolInvocation, t: AppMessages) {
  return t[getAgentToolLabelKey(tool, "running")];
}

function getToolTimelineLabel(tool: AgentToolInvocation, t: AppMessages) {
  if (isToolFailure(tool)) {
    return t[getAgentToolLabelKey(tool, "error")];
  }

  if (isToolRunning(tool.state)) {
    return getToolActivityLabel(tool, t);
  }

  return t[getAgentToolLabelKey(tool, "complete")];
}

function getEditsPreviewKey(edits: AgentResumeEditSuggestion[]) {
  return JSON.stringify(
    edits.map((edit) => ({
      id: edit.id,
      operation: edit.operation,
      replacement: edit.replacement,
      status: edit.status,
      target: edit.target,
    })),
  );
}

function AgentTypingDots({ label }: { label: string }) {
  return (
    <div
      aria-label={label}
      className="mt-2 inline-flex h-5 items-center gap-1.5 pl-1 text-muted-foreground"
      role="status"
    >
      <span className="sr-only">{label}</span>
      <span className="agent-typing-dot size-2 rounded-full bg-current [animation-delay:0ms]" />
      <span className="agent-typing-dot size-2 rounded-full bg-current [animation-delay:140ms]" />
      <span className="agent-typing-dot size-2 rounded-full bg-current [animation-delay:280ms]" />
    </div>
  );
}

function AgentToolShimmerStatus({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <div
      aria-label={label}
      className={cn(
        "flex min-w-0 items-center justify-start text-xs font-medium",
        className,
      )}
      role="status"
    >
      <Shimmer
        as="span"
        className="max-w-full truncate"
        duration={1.6}
        spread={1.6}
      >
        {label}
      </Shimmer>
    </div>
  );
}

function AgentUserMessage({
  copied,
  disabled,
  editedText,
  isEditing,
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
}: {
  copied: boolean;
  disabled: boolean;
  editedText: string;
  isEditing: boolean;
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
}) {
  const submitDisabled = disabled || !editedText.trim();
  const hasText = Boolean(message.text.trim());
  const executionStatus = message.execution?.status;
  const canRetry =
    retryable &&
    (executionStatus === "failed" || executionStatus === "cancelled");

  return (
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
            disabled={disabled}
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
            disabled={disabled}
            onClick={onStartEdit}
          >
            <Pencil className="size-3" />
          </MessageAction>
        </MessageActions>
      ) : null}
    </div>
  );
}

function formatCountMessage(
  template: string,
  count: number,
  failedCount = 0,
) {
  return template
    .replace("{count}", String(count))
    .replace("{failed}", String(failedCount));
}

function getEditSummaryLabel(edit: AgentResumeEditSuggestion) {
  return edit.title.trim() || edit.target.trim() || edit.id;
}

function toReadableDiffValue(value: unknown) {
  if (typeof value === "string") {
    return value.trim();
  }

  if (!isRecord(value)) {
    return "";
  }

  const fields = [
    value.title,
    value.subtitle,
    value.organization,
    value.role,
    value.description,
    value.summary,
  ]
    .filter((field): field is string => typeof field === "string")
    .map((field) => field.trim())
    .filter(Boolean);

  if (Array.isArray(value.highlights)) {
    fields.push(
      ...value.highlights
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean),
    );
  }

  if (fields.length) {
    return fields.join("\n");
  }

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

function getEditObservationMap(tools: AgentToolInvocation[]) {
  const map = new Map<string, { before?: string; after?: string }>();

  tools.forEach((tool) => {
    if (!isAgentEditExecutionTool(tool) || !isRecord(tool.output)) {
      return;
    }

    const observations = tool.output.observations;
    if (!Array.isArray(observations)) {
      return;
    }

    observations.forEach((observation) => {
      if (!isRecord(observation) || typeof observation.target !== "string") {
        return;
      }

      map.set(observation.target, {
        before: toReadableDiffValue(observation.before),
        after: toReadableDiffValue(observation.after),
      });
    });
  });

  return map;
}

function AgentToolDetailsDisclosure({
  tools,
  t,
}: {
  tools: AgentToolInvocation[];
  t: AppMessages;
}) {
  const completedTools = getVisibleCompletedTools(tools);
  const failedToolCount = completedTools.filter(isToolFailure).length;
  const [isOpen, setIsOpen] = useState(false);

  if (completedTools.length === 0) {
    return null;
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className="text-xs">
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="group/details h-auto max-w-full gap-1.5 px-1 py-0.5 text-xs font-medium leading-5 text-muted-foreground"
        >
          <SquareTerminal className="size-3.5" />
          <span>
            {formatCountMessage(
              failedToolCount === completedTools.length
                ? t.agentToolDetailsFailed
                : failedToolCount > 0
                  ? t.agentToolDetailsPartial
                  : t.agentToolDetailsComplete,
              completedTools.length,
              failedToolCount,
            )}
          </span>
          <ChevronRight
            className={cn(
              "size-3.5 transition-transform duration-200",
              isOpen && "rotate-90",
            )}
          />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 space-y-1 pl-6 text-xs leading-5 text-muted-foreground">
        {completedTools.map((tool) => {
          const errorDetail =
            tool.state === "output-error" && tool.errorText?.trim()
              ? tool.errorText.trim().slice(0, 320)
              : null;

          return (
            <div key={`${tool.id}-${tool.state}`} className="break-words">
              <p>{getToolTimelineLabel(tool, t)}</p>
              {errorDetail ? (
                <p className="mt-0.5 text-destructive">{errorDetail}</p>
              ) : null}
            </div>
          );
        })}
      </CollapsibleContent>
    </Collapsible>
  );
}

function AgentTimelineToolPart({
  tools,
  t,
}: {
  tools: AgentToolInvocation[];
  t: AppMessages;
}) {
  const runningTool = tools.find((tool) => isToolRunning(tool.state));

  if (runningTool) {
    return (
      <AgentToolShimmerStatus
        className="text-sm"
        label={getToolActivityLabel(runningTool, t)}
      />
    );
  }

  return <AgentToolDetailsDisclosure tools={tools} t={t} />;
}

function AgentMessageTimeline({
  parts,
  removeMarkdownTables,
  sources,
  tools,
  t,
}: {
  parts: AgentTimelinePart[];
  removeMarkdownTables?: boolean;
  sources: AgentSource[] | undefined;
  tools: AgentToolInvocation[];
  t: AppMessages;
}) {
  const visibleParts = parts.filter((part) => {
    if (part.type === "text") {
      return Boolean(part.text?.trim());
    }

    return Boolean(part.toolIds?.length);
  });
  const lastTextPartId = [...visibleParts]
    .reverse()
    .find((part) => part.type === "text")?.id;
  const visibleToolIds = getVisibleToolIds(tools);

  if (visibleParts.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {visibleParts.map((part) => {
        if (part.type === "text") {
          return (
            <div key={part.id}>
              <AgentAssistantResponse
                removeMarkdownTables={removeMarkdownTables}
                sources={part.id === lastTextPartId ? sources : undefined}
                text={part.text ?? ""}
              />
            </div>
          );
        }

        const partTools = tools.filter(
          (tool) =>
            part.toolIds?.includes(tool.id) &&
            (isToolRunning(tool.state) || visibleToolIds.has(tool.id)),
        );

        if (partTools.length === 0) {
          return null;
        }

        return (
          <AgentTimelineToolPart
            key={part.id}
            tools={partTools}
            t={t}
          />
        );
      })}
    </div>
  );
}

function AgentChangeSummary({
  edits,
  observations,
  qualityWarningCount,
  transactionState,
  hasAgentDraft,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  shouldShowDraftActions,
  t,
}: {
  edits: AgentResumeEditSuggestion[];
  observations: Map<string, { before?: string; after?: string }>;
  qualityWarningCount: number;
  transactionState: AgentTransactionState | undefined;
  hasAgentDraft: boolean;
  onApplyAgentDraft: () => void;
  onDiscardAgentDraft: () => void;
  shouldShowDraftActions: boolean;
  t: AppMessages;
}) {
  if (edits.length === 0) {
    return null;
  }

  const isCommitted = transactionState === "committed";

  return (
    <div className="mt-4 rounded-2xl border border-border/70 bg-muted/25 p-3">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        <ClipboardList className="size-3.5" />
        {t.agentChangeSummaryTitle}
      </div>
      {isCommitted ? (
        <p className="mt-2 text-sm font-medium text-foreground">
          {formatCountMessage(t.agentReviewReady, edits.length)}
        </p>
      ) : null}
      {hasAgentDraft && isCommitted ? (
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {t.agentDraftSynced}
        </p>
      ) : null}
      {qualityWarningCount > 0 ? (
        <p className="mt-1 text-xs leading-5 text-amber-700 dark:text-amber-400">
          {formatCountMessage(t.agentQualityWarnings, qualityWarningCount)}
        </p>
      ) : null}
      <div className="mt-3 max-h-72 space-y-1.5 overflow-y-auto pr-1 text-xs leading-5 text-muted-foreground">
        {edits.map((edit) => {
          const observation = observations.get(edit.target);
          const hasDiff = Boolean(observation?.before || observation?.after);

          return (
            <details
              key={edit.id}
              className="rounded-xl bg-background/45 px-2.5 py-1.5"
              open={hasDiff && edits.length === 1}
            >
              <summary className="flex cursor-pointer list-none gap-2 marker:hidden">
                <span
                  aria-hidden="true"
                  className="mt-2 size-1 rounded-full bg-current"
                />
                <span className="min-w-0 flex-1 break-words">
                  {getEditSummaryLabel(edit)}
                </span>
                {hasDiff ? (
                  <ChevronDown className="mt-1 size-3.5 shrink-0" />
                ) : null}
              </summary>
              {hasDiff ? (
                <div className="mt-2 grid gap-2">
                  {observation?.before ? (
                    <div>
                      <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.14em]">
                        {t.agentDiffBefore}
                      </div>
                      <p className="whitespace-pre-wrap rounded-lg bg-muted/40 p-2">
                        {observation.before}
                      </p>
                    </div>
                  ) : null}
                  {observation?.after ? (
                    <div>
                      <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.14em]">
                        {t.agentDiffAfter}
                      </div>
                      <p className="whitespace-pre-wrap rounded-lg bg-emerald-500/10 p-2 text-foreground">
                        {observation.after}
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </details>
          );
        })}
      </div>
      {shouldShowDraftActions ? (
        <div className="mt-3 flex gap-2">
          <Button
            type="button"
            size="sm"
            className="h-8 flex-1 rounded-xl text-xs"
            onClick={onApplyAgentDraft}
          >
            <Check className="mr-1.5 size-3.5" />
            {t.agentApplyDraft}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 flex-1 rounded-xl text-xs"
            onClick={onDiscardAgentDraft}
          >
            <RotateCcw className="mr-1.5 size-3.5" />
            {t.agentDiscardDraft}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function CopilotPanel({
  mode = "docked",
  resumeId,
  t,
  locale,
  resume,
  jobBrief,
  onJobBriefChange,
  keywordMatch,
  modelConfigs,
  selectedModelId,
  onSelectedModelChange,
  hasAgentDraft,
  agentDraftState,
  onPreviewAgentEdits,
  onRollbackAgentDraft,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  onOpenModelSettings,
  onBeforeSend,
}: {
  mode?: "docked" | "sheet";
  resumeId?: string;
  t: AppMessages;
  locale: Locale;
  resume: ResumeData;
  jobBrief: string;
  onJobBriefChange: (value: string) => void;
  keywordMatch: KeywordMatch;
  modelConfigs: ModelConfig[];
  selectedModelId: string;
  onSelectedModelChange: (modelId: string) => void;
  hasAgentDraft: boolean;
  agentDraftState: AgentDraftState | null;
  onPreviewAgentEdits: (
    edits: AgentResumeEditSuggestion[],
    baseResume: ResumeData,
    sourceMessageId?: string,
    transactionState?: AgentTransactionState,
  ) => void;
  onRollbackAgentDraft: (sourceMessageId?: string) => void;
  onApplyAgentDraft: () => void;
  onDiscardAgentDraft: () => void;
  onOpenModelSettings: () => void;
  onBeforeSend?: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<AgentPanelMessage[]>([]);
  const [streamingMessage, setStreamingMessage] =
    useState<AgentPanelMessage | null>(null);
  const [isResponding, setIsResponding] = useState(false);
  const [isSubmittingPrompt, setIsSubmittingPrompt] = useState(false);
  const [sessionLoadError, setSessionLoadError] = useState(false);
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0);
  const [attachmentUploadProgress, setAttachmentUploadProgress] = useState<
    number | null
  >(null);
  const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingMessageText, setEditingMessageText] = useState("");
  const [promptLocalAttachmentCount, setPromptLocalAttachmentCount] =
    useState(0);
  const [referencedAttachments, setReferencedAttachments] = useState<
    AgentChatAttachment[]
  >([]);
  const replyTimerRef = useRef<number | null>(null);
  const pendingSendRef = useRef<PendingAgentSend | null>(null);
  // Only the send that published the provisional message may remove it.
  // Loading authoritative history revokes this ownership before replacing UI state.
  const optimisticMessageOwnerRef = useRef<string | null>(null);
  const promptSubmissionRef = useRef(false);
  const referencedAttachmentsRef = useRef<AgentChatAttachment[]>([]);
  const copyTimerRef = useRef<number | null>(null);
  const activeRequestAbortRef = useRef<AbortController | null>(null);
  const activeUploadAbortRef = useRef<AbortController | null>(null);
  const activeRunRef = useRef<AgentRunResponse | null>(null);
  const composerRef = useRef<HTMLElement | null>(null);
  const conversationLayoutRef = useRef<HTMLDivElement | null>(null);
  const conversationContextRef = useRef<StickToBottomContext | null>(null);
  const stopRequestedRef = useRef(false);
  const previewedEditsKeyRef = useRef<string | null>(null);
  const requestResumeRef = useRef<ResumeData>(resume);
  const currentResumeIdRef = useRef(resumeId);
  const sessionRevisionRef = useRef<string | null>(null);
  const sessionReadyPromiseRef = useRef<Promise<void> | null>(null);
  const isRespondingRef = useRef(isResponding);
  const onPreviewAgentEditsRef = useRef(onPreviewAgentEdits);
  const onRollbackAgentDraftRef = useRef(onRollbackAgentDraft);
  const transientStatusTextsRef = useRef(t.agentTransientModelStatusTexts);
  const requestFailedTextRef = useRef(t.agentRequestFailed);
  onPreviewAgentEditsRef.current = onPreviewAgentEdits;
  onRollbackAgentDraftRef.current = onRollbackAgentDraft;
  transientStatusTextsRef.current = t.agentTransientModelStatusTexts;
  requestFailedTextRef.current = t.agentRequestFailed;
  currentResumeIdRef.current = resumeId;
  isRespondingRef.current = isResponding;
  referencedAttachmentsRef.current = referencedAttachments;
  const selectedModel = useMemo(
    () =>
      modelConfigs.find((config) => config.id === selectedModelId) ??
      modelConfigs[0] ??
      null,
    [modelConfigs, selectedModelId],
  );
  const modelGroups = useMemo(() => {
    const grouped = new Map<string, { items: ModelConfig[] }>();

    modelConfigs.forEach((config) => {
      const provider = getModelProvider(config);
      const current = grouped.get(provider.label);

      if (current) {
        current.items.push(config);
        return;
      }

      grouped.set(provider.label, {
        items: [config],
      });
    });

    return Array.from(grouped.entries());
  }, [modelConfigs]);
  const visibleMessages = useMemo(
    () => mergeStreamingAgentMessage(messages, streamingMessage),
    [messages, streamingMessage],
  );
  const hasConfiguredModel = Boolean(selectedModel);
  const promptAttachmentCapacity = Math.max(
    0,
    MAX_AGENT_ATTACHMENTS - referencedAttachments.length,
  );

  const cancelScheduledSend = useCallback((rollback: boolean) => {
    if (replyTimerRef.current === null) {
      return false;
    }

    window.clearTimeout(replyTimerRef.current);
    replyTimerRef.current = null;
    const pending = pendingSendRef.current;
    pendingSendRef.current = null;
    const ownsOptimisticMessage = Boolean(
      pending &&
        isPendingSendOwner(
          optimisticMessageOwnerRef.current,
          pending.optimisticMessageId,
          pending.resumeId,
          currentResumeIdRef.current,
        ),
    );

    if (rollback && pending && ownsOptimisticMessage) {
      setMessages(pending.rollbackMessages);
    }
    if (ownsOptimisticMessage) {
      optimisticMessageOwnerRef.current = null;
    }
    pending?.resolve("cancelled");
    isRespondingRef.current = false;
    setIsResponding(false);
    return true;
  }, []);

  const refreshAgentSession = useCallback(
    async (expectedResumeId: string, replaceMessages = false) => {
      const session = await loadAgentSession(expectedResumeId);
      if (expectedResumeId !== currentResumeIdRef.current) {
        return null;
      }

      sessionRevisionRef.current = session.revision;
      if (replaceMessages) {
        optimisticMessageOwnerRef.current = null;
        setMessages(
          toPanelMessages(session, ALL_AGENT_TRANSIENT_MODEL_STATUS_TEXTS),
        );
      }
      return session;
    },
    [],
  );

  useLayoutEffect(() => {
    const composer = composerRef.current;
    const conversationLayout = conversationLayoutRef.current;

    if (!composer || !conversationLayout) {
      return;
    }

    let previousHeight = -1;
    const syncComposerHeight = () => {
      const nextHeight = composer.getBoundingClientRect().height;

      if (nextHeight === previousHeight) {
        return;
      }

      const conversation = conversationContextRef.current;
      const shouldFollowBottom = Boolean(
        conversation?.state.isAtBottom &&
          !conversation.state.escapedFromLock,
      );

      previousHeight = nextHeight;
      conversationLayout.style.setProperty(
        "--agent-composer-height",
        `${nextHeight}px`,
      );
      conversationLayout.style.setProperty(
        "--agent-composer-midpoint",
        `${nextHeight / 2}px`,
      );

      // Read the lock before changing the safe area: the layout mutation can
      // temporarily make an attached conversation appear away from the bottom.
      if (shouldFollowBottom) {
        void conversation?.scrollToBottom({ animation: "instant" });
      }
    };

    // The composer overlays the scroll viewport. Measure its real height so
    // attachments and multiline input never depend on a fixed bottom offset.
    syncComposerHeight();
    const resizeObserver = new ResizeObserver(syncComposerHeight);
    resizeObserver.observe(composer);
    return () => resizeObserver.disconnect();
  }, []);

  const syncPreviewEdits = useCallback(
    (
      edits: AgentResumeEditSuggestion[] | undefined,
      baseResume: ResumeData,
      sourceMessageId: string | undefined,
      transactionState: AgentTransactionState | undefined,
    ) => {
      if (
        !edits?.length ||
        (transactionState !== "provisional" &&
          transactionState !== "committed")
      ) {
        return;
      }

      const key = `${transactionState}:${getEditsPreviewKey(edits)}`;
      if (previewedEditsKeyRef.current === key) {
        return;
      }

      previewedEditsKeyRef.current = key;
      onPreviewAgentEditsRef.current(
        edits,
        baseResume,
        sourceMessageId,
        transactionState,
      );
    },
    [],
  );

  const consumeRunStream = useCallback(
    async (
      start: (options: AgentChatStreamOptions) => Promise<AgentChatResponse>,
      abortController: AbortController,
      notifyOnFailure = true,
    ): Promise<AgentRunStatus> => {
      let streamedMessageId: string | undefined;
      const expectedResumeId = currentResumeIdRef.current;

      try {
        const response = await start({
          onRun: (run) => {
            if (abortController.signal.aborted) {
              return;
            }

            requestResumeRef.current = run.baseResume;
            activeRunRef.current = run.status === "active" ? run : null;

            if (run.status === "active" && stopRequestedRef.current) {
              void stopAgentRun(run.id).catch((error) => {
                stopRequestedRef.current = false;
                console.error("Failed to stop agent run.", error);
                if (!isApiErrorToastShown(error)) {
                  toast.error(requestFailedTextRef.current, {
                    closeButton: true,
                  });
                }
              });
            }
          },
          onMessage: (streamedMessage) => {
            if (abortController.signal.aborted) {
              return;
            }

            streamedMessageId = streamedMessage.id;
            const panelMessage = toAssistantPanelMessage(
              streamedMessage,
              transientStatusTextsRef.current,
            );
            setStreamingMessage(panelMessage);

            if (streamedMessage.transactionState === "rolled_back") {
              onRollbackAgentDraftRef.current(streamedMessage.id);
              return;
            }

            syncPreviewEdits(
              streamedMessage.edits,
              requestResumeRef.current,
              streamedMessage.id,
              streamedMessage.transactionState,
            );
          },
          signal: abortController.signal,
        });

        if (abortController.signal.aborted) {
          return "cancelled";
        }

        const finalMessage = toAssistantPanelMessage(
          response.message,
          transientStatusTextsRef.current,
        );
        const shouldRollback =
          response.message.transactionState === "rolled_back" ||
          response.status === "cancelled" ||
          response.status === "failed";

        if (shouldRollback) {
          onRollbackAgentDraftRef.current(response.message.id);
        } else {
          syncPreviewEdits(
            response.message.edits,
            requestResumeRef.current,
            response.message.id,
            response.message.transactionState,
          );
        }

        // Failed and cancelled runs are intentionally not persisted by the
        // backend. Do not leave a local-only assistant message that vanishes
        // the next time the authoritative session is loaded.
        if (response.messageDone && response.status === "completed") {
          setMessages((currentMessages) => {
            const existingIndex = currentMessages.findIndex(
              (message) => message.id === finalMessage.id,
            );

            if (existingIndex < 0) {
              return [...currentMessages, finalMessage];
            }

            return currentMessages.map((message, index) =>
              index === existingIndex ? finalMessage : message,
            );
          });
        }
        return response.status;
      } catch (error) {
        if (isAbortError(error)) {
          return "cancelled";
        }

        // A non-retryable subscription failure means this browser can no
        // longer observe a commit. Never leave its provisional preview active.
        onRollbackAgentDraftRef.current(streamedMessageId);
        console.error("Failed to consume agent run.", error);
        if (notifyOnFailure && !isApiErrorToastShown(error)) {
          toast.error(requestFailedTextRef.current, {
            closeButton: true,
          });
        }
        return "failed";
      } finally {
        if (expectedResumeId) {
          try {
            await refreshAgentSession(expectedResumeId, true);
          } catch (error) {
            if (!isAbortError(error)) {
              console.error(
                "Failed to refresh the Agent session revision.",
                error,
              );
            }
          }
        }

        if (activeRequestAbortRef.current === abortController) {
          activeRequestAbortRef.current = null;
          activeRunRef.current = null;
          stopRequestedRef.current = false;
          setStreamingMessage(null);
          setIsResponding(false);
        }
      }
    },
    [refreshAgentSession, syncPreviewEdits],
  );

  useEffect(() => {
    let cancelled = false;
    const abortController = new AbortController();
    let resolveSessionReady: () => void = () => undefined;
    let sessionReadyResolved = false;
    const sessionReadyPromise = new Promise<void>((resolve) => {
      resolveSessionReady = resolve;
    });
    const markSessionReady = () => {
      if (sessionReadyResolved) {
        return;
      }
      sessionReadyResolved = true;
      resolveSessionReady();
    };

    activeRequestAbortRef.current?.abort();
    activeRequestAbortRef.current = abortController;
    sessionReadyPromiseRef.current = sessionReadyPromise;
    activeRunRef.current = null;
    stopRequestedRef.current = false;
    previewedEditsKeyRef.current = null;

    cancelScheduledSend(false);

    setMessages([]);
    setStreamingMessage(null);
    setIsResponding(false);
    setCopiedMessageId(null);
    setEditingMessageId(null);
    setEditingMessageText("");
    setPromptLocalAttachmentCount(0);
    setSessionLoadError(false);
    sessionRevisionRef.current = null;
    optimisticMessageOwnerRef.current = null;
    referencedAttachmentsRef.current = [];
    setReferencedAttachments([]);

    if (!resumeId) {
      markSessionReady();
      sessionReadyPromiseRef.current = null;
      activeRequestAbortRef.current = null;
      return () => {
        cancelled = true;
        abortController.abort();
      };
    }

    void (async () => {
      try {
        const session = await loadAgentSession(resumeId);
        if (
          cancelled ||
          activeRequestAbortRef.current !== abortController
        ) {
          return;
        }

        setMessages(
          toPanelMessages(session, ALL_AGENT_TRANSIENT_MODEL_STATUS_TEXTS),
        );
        sessionRevisionRef.current = session.revision;

        const run = await loadActiveAgentRun(resumeId);
        if (
          cancelled ||
          activeRequestAbortRef.current !== abortController ||
          !run ||
          run.status !== "active"
        ) {
          markSessionReady();
          if (activeRequestAbortRef.current === abortController) {
            activeRequestAbortRef.current = null;
          }
          return;
        }

        requestResumeRef.current = run.baseResume;
        activeRunRef.current = run;
        isRespondingRef.current = true;
        setIsResponding(true);
        markSessionReady();
        await consumeRunStream(
          (options) => connectAgentRun(run, options),
          abortController,
        );
      } catch (error) {
        markSessionReady();
        if (
          !cancelled &&
          activeRequestAbortRef.current === abortController &&
          !isAbortError(error)
        ) {
          console.error("Failed to restore agent session.", error);
          setSessionLoadError(true);
        }
        if (activeRequestAbortRef.current === abortController) {
          activeRequestAbortRef.current = null;
        }
      } finally {
        markSessionReady();
        if (sessionReadyPromiseRef.current === sessionReadyPromise) {
          sessionReadyPromiseRef.current = null;
        }
      }
    })();

    return () => {
      cancelled = true;
      markSessionReady();
      abortController.abort();
      if (sessionReadyPromiseRef.current === sessionReadyPromise) {
        sessionReadyPromiseRef.current = null;
      }
      if (activeRequestAbortRef.current === abortController) {
        activeRequestAbortRef.current = null;
      }
    };
  }, [
    cancelScheduledSend,
    consumeRunStream,
    resumeId,
    sessionLoadAttempt,
  ]);

  useEffect(() => {
    return () => {
      if (replyTimerRef.current !== null) {
        window.clearTimeout(replyTimerRef.current);
        replyTimerRef.current = null;
      }
      pendingSendRef.current?.resolve("cancelled");
      pendingSendRef.current = null;
      if (copyTimerRef.current) {
        window.clearTimeout(copyTimerRef.current);
      }
      activeRequestAbortRef.current?.abort();
      activeUploadAbortRef.current?.abort();
    };
  }, []);

  const handleModelSelect = useCallback(
    (modelId: string) => {
      onSelectedModelChange(modelId);
      setModelSelectorOpen(false);
    },
    [onSelectedModelChange],
  );

  const copyUserMessage = useCallback(
    async (message: AgentPanelMessage) => {
      try {
        await navigator.clipboard.writeText(message.text);
        setCopiedMessageId(message.id);

        if (copyTimerRef.current) {
          window.clearTimeout(copyTimerRef.current);
        }

        copyTimerRef.current = window.setTimeout(() => {
          setCopiedMessageId((currentId) =>
            currentId === message.id ? null : currentId,
          );
          copyTimerRef.current = null;
        }, 1200);
      } catch (error) {
        console.error("Failed to copy agent user message.", error);
      }
    },
    [],
  );

  const downloadHistoryAttachment = useCallback(
    async (file: AgentChatAttachment) => {
      if (!resumeId || !file.id) {
        return;
      }

      try {
        const response = await downloadAgentAttachment(resumeId, file.id);
        const objectUrl = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = file.filename || t.agentAttachmentFallback;
        link.hidden = true;
        document.body.append(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      } catch (error) {
        console.error("Failed to download Agent attachment.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(t.agentAttachmentDownloadFailed, {
            closeButton: true,
          });
        }
      }
    },
    [resumeId, t.agentAttachmentDownloadFailed, t.agentAttachmentFallback],
  );

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

  function startEditingUserMessage(message: AgentPanelMessage) {
    if (isResponding) {
      return;
    }

    setEditingMessageId(message.id);
    setEditingMessageText(message.text);
  }

  function cancelEditingUserMessage() {
    setEditingMessageId(null);
    setEditingMessageText("");
  }

  async function submitPrompt(message: PromptInputMessage) {
    if (
      isSubmittingPrompt ||
      promptSubmissionRef.current ||
      isResponding
    ) {
      throw new Error("An Agent prompt submission is already in progress.");
    }

    if (!hasConfiguredModel) {
      toast.info(t.agentModelRequiredHint, {
        closeButton: true,
      });
      throw new Error("An Agent model must be configured before sending.");
    }

    if (
      message.files.length + referencedAttachments.length >
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
                  Math.min(99, Math.round((uploadedBytes / totalBytes) * 100)),
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
        throw new Error("The active resume changed while uploading attachments.");
      }

      const completion = sendPrompt(message.text, [
        ...referencedAttachments,
        ...uploadedFiles,
      ]);
      requestAccepted = true;
      referencedAttachmentsRef.current = [];
      setReferencedAttachments([]);

      // PromptInput clears its draft as soon as the uploaded snapshot has been
      // accepted. The Agent run continues independently; failed or cancelled
      // runs remove only uploads that never became protected chat history.
      void completion
        .then(async (status) => {
          if (
            status !== "completed" &&
            resumeId &&
            uploadedFiles.length > 0
          ) {
            await deletePendingUploads(resumeId, uploadedFiles);
          }
        })
        .catch(async (error) => {
          if (resumeId && uploadedFiles.length > 0) {
            await deletePendingUploads(resumeId, uploadedFiles);
          }
          console.error("Failed to finish the Agent prompt submission.", error);
        })
        .finally(() => {
          promptSubmissionRef.current = false;
        });
    } catch (error) {
      if (resumeId && uploadedFiles.length > 0) {
        await deletePendingUploads(resumeId, uploadedFiles);
      }

      if (!isAbortError(error)) {
        console.error("Failed to upload agent attachment.", error);
      }
      if (!isAbortError(error) && !isApiErrorToastShown(error)) {
        toast.error(t.agentAttachmentUploadFailed, {
          closeButton: true,
        });
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
  }

  const stopResponding = useCallback(() => {
    if (isSubmittingPrompt && activeUploadAbortRef.current) {
      activeUploadAbortRef.current.abort();
      return;
    }

    if (cancelScheduledSend(true)) {
      return;
    }

    if (stopRequestedRef.current) {
      return;
    }

    stopRequestedRef.current = true;
    const activeRun = activeRunRef.current;

    // Keep the subscriber connected so the rollback event can clear any
    // provisional preview before the run reports its terminal state.
    if (activeRun) {
      void stopAgentRun(activeRun.id).catch((error) => {
        stopRequestedRef.current = false;
        console.error("Failed to stop agent run.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(requestFailedTextRef.current, {
            closeButton: true,
          });
        }
      });
      return;
    }

    if (!activeRequestAbortRef.current) {
      stopRequestedRef.current = false;
      setIsResponding(false);
    }
  }, [cancelScheduledSend, isSubmittingPrompt]);

  async function submitEditedUserMessage(message: AgentPanelMessage) {
    const nextText = editingMessageText.trim();

    if (!nextText) {
      toast.info(t.agentEditEmpty, {
        closeButton: true,
      });
      return;
    }

    const messageIndex = messages.findIndex((item) => item.id === message.id);
    if (messageIndex < 0 || isResponding) {
      return;
    }

    cancelEditingUserMessage();
    await sendPrompt(nextText, message.files ?? [], {
      baseMessages: messages.slice(0, messageIndex),
      messageId: message.id,
      replaceSessionBeforeSend: true,
    });
  }

  async function retryUserMessage(message: AgentPanelMessage) {
    const messageIndex = messages.findIndex((item) => item.id === message.id);
    if (messageIndex < 0 || isResponding) {
      return;
    }

    await sendPrompt(message.text, message.files ?? [], {
      baseMessages: messages.slice(0, messageIndex),
      messageId: message.id,
    });
  }

  async function sendPrompt(
    text: string,
    files: AgentChatAttachment[] = [],
    options: {
      baseMessages?: AgentPanelMessage[];
      messageId?: string;
      replaceSessionBeforeSend?: boolean;
    } = {},
  ): Promise<AgentRunStatus> {
    const prompt = text.trim();

    if ((!prompt && files.length === 0) || isResponding) {
      return "cancelled";
    }

    await onBeforeSend?.();
    await sessionReadyPromiseRef.current;

    if (isRespondingRef.current) {
      return "cancelled";
    }
    if (resumeId && !sessionRevisionRef.current) {
      const session = await refreshAgentSession(resumeId, true);
      if (!session) {
        return "failed";
      }
    }

    const baseMessages = options.baseMessages ?? messages;
    const rollbackMessages = messages;
    const looksLikeJobBrief = isLikelyJobBriefPrompt(prompt);
    const nextJobBrief = looksLikeJobBrief ? prompt : jobBrief;
    const nextKeywordMatch = looksLikeJobBrief
      ? getKeywordMatch(resume, nextJobBrief, 0, t)
      : keywordMatch;
    const userMessage: AgentPanelMessage = {
      files,
      id: options.messageId ?? createId("agent-user"),
      role: "user",
      text: prompt,
    };
    const nextMessages = [...baseMessages, userMessage];
    const apiMessages = nextMessages.map(toConversationMessage);

    // A session restore may still be in flight when the user starts typing.
    // Abort it before publishing the optimistic message so stale history can
    // never replace the newly submitted prompt.
    activeRequestAbortRef.current?.abort();
    activeRequestAbortRef.current = null;
    setSessionLoadError(false);
    cancelScheduledSend(false);
    setIsResponding(true);
    isRespondingRef.current = true;
    setMessages(nextMessages);
    optimisticMessageOwnerRef.current = userMessage.id;
    setStreamingMessage(null);
    previewedEditsKeyRef.current = null;
    requestResumeRef.current = resume;

    if (looksLikeJobBrief) {
      onJobBriefChange(prompt);
    }

    return new Promise<AgentRunStatus>((resolve) => {
      pendingSendRef.current = {
        optimisticMessageId: userMessage.id,
        resolve,
        resumeId,
        rollbackMessages,
      };
      replyTimerRef.current = window.setTimeout(() => {
        const pending = pendingSendRef.current;
        pendingSendRef.current = null;
        replyTimerRef.current = null;

        void (async () => {
          const abortController = new AbortController();
          let failure: unknown;
          let status: AgentRunStatus = "failed";
          let runAccepted = false;
          let sessionReconciled = false;

          activeRequestAbortRef.current?.abort();
          activeRequestAbortRef.current = abortController;

          try {
            if (options.replaceSessionBeforeSend && resumeId) {
              const revision = sessionRevisionRef.current;
              if (!revision) {
                await refreshAgentSession(resumeId, true);
                sessionReconciled = true;
                throw new Error(
                  "Cannot replace Agent history before loading its revision.",
                );
              }

              const session = await replaceAgentSession(resumeId, {
                locale,
                messages: apiMessages,
                revision,
              });
              sessionRevisionRef.current = session.revision;
              runAccepted = true;
            }

            if (abortController.signal.aborted) {
              status = "cancelled";
            } else {
              status = await consumeRunStream(
                (streamOptions) =>
                  sendAgentChatMessage(
                    {
                      appliedActions: [],
                      clientTurnId: userMessage.id,
                      conversation: apiMessages,
                      expectedRevision:
                        sessionRevisionRef.current ?? undefined,
                      files,
                      jobBrief: nextJobBrief,
                      keywordMatch: nextKeywordMatch,
                      locale,
                      message: toConversationMessage(userMessage),
                      messages: apiMessages,
                      modelConfig: selectedModel,
                      prompt,
                      resume,
                      resumeId,
                      draftState: agentDraftState,
                      stream: true,
                    },
                    {
                      ...streamOptions,
                      onRun: (run) => {
                        runAccepted = true;
                        streamOptions.onRun?.(run);
                      },
                    },
                  ),
                abortController,
                false,
              );
            }
          } catch (error) {
            failure = error;
            status = isAbortError(error) ? "cancelled" : "failed";
            if (
              status === "failed" &&
              resumeId &&
              (isApiErrorCode(error, "AGENT_SESSION_REVISION_CONFLICT") ||
                isApiErrorCode(error, "AGENT_SESSION_TURN_CONFLICT"))
            ) {
              try {
                const session = await refreshAgentSession(resumeId, true);
                sessionReconciled = Boolean(session);
                if (sessionReconciled) {
                  onRollbackAgentDraftRef.current();
                }
              } catch (refreshError) {
                console.error(
                  "Failed to reconcile the Agent session after a conflict.",
                  refreshError,
                );
              }
            }
            if (status === "failed") {
              console.error(
                "Failed to replace the agent session before editing.",
                error,
              );
            }
          } finally {
            const ownsOptimisticMessage = Boolean(
              pending &&
                isPendingSendOwner(
                  optimisticMessageOwnerRef.current,
                  pending.optimisticMessageId,
                  pending.resumeId,
                  currentResumeIdRef.current,
                ),
            );
            if (
              status !== "completed" &&
              !sessionReconciled &&
              pending &&
              ownsOptimisticMessage &&
              shouldRollbackOptimisticAgentMessages({
                replaceSessionBeforeSend: Boolean(
                  options.replaceSessionBeforeSend,
                ),
                runAccepted,
              })
            ) {
              setMessages(pending.rollbackMessages);
            }
            if (ownsOptimisticMessage) {
              optimisticMessageOwnerRef.current = null;
            }

            if (status === "failed" && !isApiErrorToastShown(failure)) {
              toast.error(requestFailedTextRef.current, {
                closeButton: true,
              });
            }

            if (activeRequestAbortRef.current === abortController) {
              activeRequestAbortRef.current = null;
              activeRunRef.current = null;
              stopRequestedRef.current = false;
              setStreamingMessage(null);
              isRespondingRef.current = false;
              setIsResponding(false);
            }
            pending?.resolve(status);
          }
        })();
      }, AGENT_REQUEST_DEBOUNCE_MS);
    });
  }

  return (
    <TooltipProvider>
      <aside
        data-mode={mode}
        className={cn(
          "agent-panel-card flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-sm print:hidden",
          mode === "docked"
            ? "h-full xl:self-start"
            : "h-full",
        )}
      >
          <div className="px-4 pb-2 pt-3">
            <h3 className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
              {t.aiTitle}
            </h3>
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            <div
              className="agent-thread-layout relative flex min-h-0 flex-1 flex-col"
              ref={conversationLayoutRef}
            >
              <Conversation
                className="min-h-0 min-w-0 flex-1 overflow-x-hidden"
                contextRef={conversationContextRef}
                initial="instant"
                resize="instant"
              >
                <ConversationContent
                  scrollClassName="agent-thread-scroll"
                  className={cn(
                    "agent-thread-safe-area min-w-0 overflow-x-hidden px-3",
                    visibleMessages.length === 0 &&
                      "h-full min-h-full flex-1 justify-center",
                  )}
                >
                  {visibleMessages.length === 0 ? (
                    <ConversationEmptyState
                      className="px-6 py-10"
                    >
                      <div className="mx-auto grid max-w-[260px] justify-items-center gap-3 text-center">
                        <p className="text-sm leading-6 text-muted-foreground">
                          {sessionLoadError
                            ? t.agentHistoryLoadFailed
                            : t.agentEmptyPrompt}
                        </p>
                        {sessionLoadError ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 rounded-xl px-3 text-xs"
                            onClick={() =>
                              setSessionLoadAttempt((attempt) => attempt + 1)
                            }
                          >
                            <RotateCcw className="mr-1.5 size-3.5" />
                            {t.agentRetry}
                          </Button>
                        ) : !hasConfiguredModel ? (
                          <Button
                            type="button"
                            size="sm"
                            className="h-8 rounded-xl px-3 text-xs"
                            onClick={onOpenModelSettings}
                          >
                            {t.openModelSettings}
                          </Button>
                        ) : null}
                      </div>
                    </ConversationEmptyState>
                  ) : (
                    <div className="grid gap-3">
                      {visibleMessages.map((message) => {
                      const response = message.response;
                      const isStreamingAssistant =
                        isResponding && streamingMessage?.id === message.id;
                      const assistantText = message.text.trim();
                      const tools = response?.tools ?? [];
                      const qualityWarningCount =
                        getAgentQualityWarningCount(tools);
                      const timeline = response?.timeline ?? [];
                      const shouldRenderTimeline = timeline.length > 0;
                      const editObservations = getEditObservationMap(tools);
                      const runningTool = tools.find((tool) =>
                        isToolRunning(tool.state),
                      );
                      const runningToolLabel = runningTool
                        ? getToolActivityLabel(runningTool, t)
                        : null;
                      const shouldShowInitialStatus =
                        isStreamingAssistant &&
                        !assistantText &&
                        !tools.length;
                      const shouldShowDraftActions =
                        hasAgentDraft &&
                        shouldShowAgentDraftActions({
                          draft: agentDraftState,
                          isResponding,
                          messageId: message.id,
                          response,
                        });
                      const shouldShowChangeSummary =
                        Boolean(response?.edits?.length) &&
                        response?.transactionState !== "rolled_back";
                      const hasRenderableAssistantContent =
                        hasAssistantRenderableContent(message);
                      const isEditingUserMessage =
                        message.role === "user" &&
                        editingMessageId === message.id;

                      return (
                        <Message
                          key={message.id}
                          from={message.role}
                          className={cn(
                            isEditingUserMessage && "w-full !max-w-full",
                          )}
                        >
                          {message.role === "user" ? (
                            <AgentUserMessage
                              copied={copiedMessageId === message.id}
                              disabled={isResponding}
                              editedText={
                                editingMessageId === message.id
                                  ? editingMessageText
                                  : message.text
                              }
                              isEditing={editingMessageId === message.id}
                              message={message}
                              t={t}
                              onCancelEdit={cancelEditingUserMessage}
                              onCopy={() => {
                                void copyUserMessage(message);
                              }}
                              onDownloadAttachment={(file) => {
                                void downloadHistoryAttachment(file);
                              }}
                              onEditTextChange={setEditingMessageText}
                              onReferenceAttachment={
                                referenceHistoryAttachment
                              }
                              onRetry={() => {
                                void retryUserMessage(message);
                              }}
                              onStartEdit={() => startEditingUserMessage(message)}
                              onSubmitEdit={() => {
                                void submitEditedUserMessage(message);
                              }}
                              retryable={
                                message.id === messages[messages.length - 1]?.id
                              }
                            />
                          ) : (
                            <MessageContent className="w-full min-w-0 max-w-full px-0 py-1 text-foreground">
                              <>
                                {shouldRenderTimeline ? (
                                  <AgentMessageTimeline
                                    parts={timeline}
                                    removeMarkdownTables={Boolean(
                                      response?.edits?.length,
                                    )}
                                    sources={response?.sources}
                                    tools={tools}
                                    t={t}
                                  />
                                ) : (
                                  <>
                                    {assistantText ? (
                                      <div>
                                        <AgentAssistantResponse
                                          removeMarkdownTables={Boolean(
                                            response?.edits?.length,
                                          )}
                                          sources={response?.sources}
                                          text={message.text}
                                        />
                                      </div>
                                    ) : null}
                                    {runningToolLabel ? (
                                      <AgentToolShimmerStatus
                                        className={assistantText ? "mt-3 text-sm" : "text-sm"}
                                        label={runningToolLabel}
                                      />
                                    ) : shouldShowInitialStatus ? (
                                      <AgentToolShimmerStatus
                                        className={assistantText ? "mt-3 text-sm" : "text-sm"}
                                        label={t.agentToolThinking}
                                      />
                                    ) : tools.length ? (
                                      <div className={assistantText ? "mt-3" : undefined}>
                                        <AgentToolDetailsDisclosure tools={tools} t={t} />
                                      </div>
                                    ) : null}
                                    {!assistantText &&
                                    isStreamingAssistant &&
                                      !hasRenderableAssistantContent &&
                                      !shouldShowInitialStatus &&
                                      !runningToolLabel ? (
                                      <AgentTypingDots label={t.agentThinking} />
                                    ) : null}
                                  </>
                                )}
                                {shouldShowChangeSummary ? (
                                  <AgentChangeSummary
                                    edits={response?.edits ?? []}
                                    observations={editObservations}
                                    qualityWarningCount={qualityWarningCount}
                                    transactionState={response?.transactionState}
                                    hasAgentDraft={hasAgentDraft}
                                    onApplyAgentDraft={onApplyAgentDraft}
                                    onDiscardAgentDraft={onDiscardAgentDraft}
                                    shouldShowDraftActions={shouldShowDraftActions}
                                    t={t}
                                  />
                                ) : null}
                              </>
                            </MessageContent>
                          )}
                        </Message>
                      );
                      })}

                      {isResponding && !streamingMessage ? (
                        <Message from="assistant">
                          <MessageContent className="w-full px-0 py-1 text-muted-foreground">
                            <AgentToolShimmerStatus
                              className="mt-2 text-sm"
                              label={t.agentToolThinking}
                            />
                          </MessageContent>
                        </Message>
                      ) : null}

                    </div>
                  )}
                </ConversationContent>
                <ConversationScrollButton className="agent-thread-scroll-button z-20" />
              </Conversation>
              <section
                className="pointer-events-none absolute inset-x-0 bottom-0 z-10 px-3 pb-3"
                ref={composerRef}
              >
                <div className="pointer-events-auto relative">
              <PromptInputProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      className={cn(
                        "rounded-[26px]",
                        !hasConfiguredModel && "cursor-not-allowed",
                      )}
                    >
                      <PromptInput
                        accept={
                          selectedModel?.supportsImage
                            ? IMAGE_ATTACHMENT_ACCEPT
                            : TEXT_ATTACHMENT_ACCEPT
                        }
                        globalDrop
                        maxFiles={promptAttachmentCapacity}
                        maxFileSize={MAX_AGENT_ATTACHMENT_BYTES}
                        multiple
                        onError={() => {
                          toast.error(t.agentAttachmentRejected, {
                            closeButton: true,
                          });
                        }}
                        onSubmit={submitPrompt}
                        className={cn(
                          "p-0 text-foreground [&_[data-slot=input-group]]:overflow-hidden [&_[data-slot=input-group]]:rounded-[26px] [&_[data-slot=input-group]]:border-border/70 [&_[data-slot=input-group]]:bg-background [&_[data-slot=input-group]]:shadow-sm",
                          !hasConfiguredModel &&
                            "[&_[data-slot=input-group]]:cursor-not-allowed",
                        )}
                      >
                        <AgentPromptAttachmentsDisplay
                          fallbackLabel={t.agentAttachmentFallback}
                          onLocalCountChange={setPromptLocalAttachmentCount}
                          onRemoveReferenced={removeReferencedAttachment}
                          referencedFiles={referencedAttachments}
                        />
                        <PromptInputBody className="px-4 pt-3">
                          <PromptInputTextarea
                            rows={1}
                            disabled={
                              !hasConfiguredModel || isSubmittingPrompt
                            }
                            placeholder={
                              hasConfiguredModel
                                ? t.agentPromptPlaceholderShort
                                : ""
                            }
                            className="min-h-[58px] max-h-[132px] px-4 pb-0 pt-3 text-[15px] leading-[22px] text-foreground placeholder:text-muted-foreground disabled:cursor-not-allowed"
                          />
                        </PromptInputBody>

                        <PromptInputFooter className="justify-between gap-2.5 px-4 pb-3.5 pt-1">
                          <PromptInputTools className="min-w-0 gap-1.5">
                            <AgentPromptAttachmentButton
                              disabled={
                                !hasConfiguredModel ||
                                isSubmittingPrompt ||
                                promptAttachmentCapacity === 0
                              }
                              label={t.agentAddAttachments}
                            />

                            <ModelSelector
                              open={modelSelectorOpen}
                              onOpenChange={setModelSelectorOpen}
                            >
                              <ModelSelectorTrigger asChild>
                                <PromptInputButton
                                  size="sm"
                                  disabled={isSubmittingPrompt}
                                  title={
                                    selectedModel ? undefined : t.agentModelConfigureHover
                                  }
                                  aria-label={
                                    selectedModel
                                      ? getModelDisplayName(selectedModel)
                                      : t.agentModelConfigureHover
                                  }
                                  className="h-8 w-fit min-w-0 max-w-none justify-start text-foreground transition-colors duration-200"
                                >
                                  {selectedModel ? (
                                    <ModelSelectorLogo
                                      provider={getModelProvider(selectedModel).id}
                                    />
                                  ) : (
                                    <span
                                      aria-hidden="true"
                                      className="size-4 shrink-0"
                                    />
                                  )}
                                  <ModelSelectorName
                                    className={cn(
                                      "flex-none overflow-visible text-clip whitespace-nowrap text-[12px] font-medium",
                                      !selectedModel && "text-muted-foreground",
                                    )}
                                  >
                                    {selectedModel
                                      ? getModelTriggerName(selectedModel)
                                      : t.agentModelNotConfigured}
                                  </ModelSelectorName>
                                </PromptInputButton>
                              </ModelSelectorTrigger>
                              <ModelSelectorContent>
                                <ModelSelectorInput
                                  placeholder={t.agentModelSearchPlaceholder}
                                />
                                <ModelSelectorList>
                                  <ModelSelectorEmpty>
                                    {modelConfigs.length === 0 ? (
                                      <div className="grid gap-3 px-4 py-5 text-center">
                                        <p className="text-sm text-muted-foreground">
                                          {t.agentNoConfiguredModels}
                                        </p>
                                        <Button
                                          type="button"
                                          size="sm"
                                          className="mx-auto h-8 rounded-xl px-3 text-xs"
                                          onClick={() => {
                                            setModelSelectorOpen(false);
                                            onOpenModelSettings();
                                          }}
                                        >
                                          {t.openModelSettings}
                                        </Button>
                                      </div>
                                    ) : (
                                      t.agentNoModelsFound
                                    )}
                                  </ModelSelectorEmpty>
                                  {modelGroups.map(([groupName, group]) => (
                                    <ModelSelectorGroup
                                      key={groupName}
                                      heading={groupName}
                                    >
                                      {group.items.map((config) => (
                                        <ModelSelectorItem
                                          key={config.id}
                                          value={config.id}
                                          onSelect={() => handleModelSelect(config.id)}
                                        >
                                          <ModelSelectorLogo
                                            provider={getModelProvider(config).id}
                                          />
                                          <div className="flex min-w-0 flex-1 flex-col">
                                            <ModelSelectorName className="truncate font-medium">
                                              {getModelDisplayName(config)}
                                            </ModelSelectorName>
                                            {getModelSecondaryName(config) ? (
                                              <span className="truncate text-xs text-muted-foreground">
                                                {getModelSecondaryName(config)}
                                              </span>
                                            ) : null}
                                          </div>
                                          {selectedModelId === config.id ? (
                                            <Check className="ml-auto size-4" />
                                          ) : (
                                            <div className="ml-auto size-4" />
                                          )}
                                        </ModelSelectorItem>
                                      ))}
                                    </ModelSelectorGroup>
                                  ))}
                                </ModelSelectorList>
                              </ModelSelectorContent>
                            </ModelSelector>
                          </PromptInputTools>

                          <AgentPromptSubmitButton
                            attachmentUploadProgress={
                              attachmentUploadProgress
                            }
                            hasConfiguredModel={hasConfiguredModel}
                            hasReferencedAttachments={
                              referencedAttachments.length > 0
                            }
                            isResponding={isResponding}
                            isSubmittingPrompt={isSubmittingPrompt}
                            onStop={stopResponding}
                            t={t}
                          />
                        </PromptInputFooter>
                      </PromptInput>
                    </div>
                  </TooltipTrigger>
                  {!hasConfiguredModel ? (
                    <TooltipContent side="top">
                      {t.agentPromptDisabledTooltip}
                    </TooltipContent>
                  ) : null}
                </Tooltip>
              </PromptInputProvider>
                </div>
            </section>
            </div>
          </div>
      </aside>
    </TooltipProvider>
  );
}
