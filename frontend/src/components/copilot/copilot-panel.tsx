import {
  Attachment,
  AttachmentPreview,
  AttachmentRemove,
  Attachments,
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
import { Textarea } from "@/components/ui/textarea";
import {
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Copy,
  FileText,
  Pencil,
  Plus,
  RotateCcw,
  SquareTerminal,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { getMessagesSync, locales, type AppMessages, type Locale } from "@/i18n";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  loadAgentSession,
  replaceAgentSession,
  sendAgentChatMessage,
} from "@/lib/agent-api";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import {
  getVisibleCompletedTools,
  getVisibleToolIds,
  isToolRunning,
} from "@/lib/agent-tool-display";
import { isPlainAgentText } from "@/lib/agent-message-rendering";
import languagePatterns from "@/lib/language-patterns.json";
import { createId, getKeywordMatch } from "@/lib/resume";
import { cn } from "@/lib/utils";
import type {
  AgentChatAttachment,
  AgentChatMessage,
  AgentConversationMessage,
  AgentDraftState,
  AgentResumeEditSuggestion,
  AgentSource,
  AgentStoredMessage,
  AgentTimelinePart,
  AgentToolInvocation,
} from "@/types/api";
import type {
  AgentSettings,
  KeywordMatch,
  ModelConfig,
  ResumeData,
} from "@/types/resume";

const AGENT_REQUEST_DEBOUNCE_MS = 420;
const MAX_ATTACHMENT_TEXT_LENGTH = 16_000;
const TEXT_ATTACHMENT_ACCEPT =
  "application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const IMAGE_ATTACHMENT_ACCEPT = `image/*,${TEXT_ATTACHMENT_ACCEPT}`;
const TEXT_ATTACHMENT_PATTERN =
  /^(text\/|application\/json|application\/xml|application\/.*\+json)/i;
const JOB_BRIEF_PROMPT_PATTERN = new RegExp(
  languagePatterns.jobBriefPrompt.map(escapeRegExp).join("|"),
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

function AgentPromptAttachmentsDisplay() {
  const attachments = usePromptInputAttachments();

  if (attachments.files.length === 0) {
    return null;
  }

  return (
    <Attachments className="px-4 pt-4" variant="inline">
      {attachments.files.map((attachment) => (
        <Attachment
          data={attachment}
          key={attachment.id}
          onRemove={() => attachments.remove(attachment.id)}
        >
          <AttachmentPreview />
          <AttachmentRemove />
        </Attachment>
      ))}
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

function isLikelyJobBriefPrompt(prompt: string) {
  const trimmed = prompt.trim();

  return (
    trimmed.length >= 140 ||
    trimmed.split(/\n+/).filter(Boolean).length >= 3 ||
    JOB_BRIEF_PROMPT_PATTERN.test(trimmed)
  );
}

function isReadableTextAttachment(file: PromptInputMessage["files"][number]) {
  const mediaType = file.mediaType ?? "";
  const filename = file.filename ?? "";

  return (
    TEXT_ATTACHMENT_PATTERN.test(mediaType) ||
    /\.(txt|md|markdown|json|csv|xml|yaml|yml)$/i.test(filename)
  );
}

async function readAttachmentContent(file: PromptInputMessage["files"][number]) {
  if (!file.url || !file.url.startsWith("blob:") || !isReadableTextAttachment(file)) {
    return undefined;
  }

  try {
    const response = await fetch(file.url);
    const text = await response.text();
    return text.slice(0, MAX_ATTACHMENT_TEXT_LENGTH);
  } catch {
    return undefined;
  }
}

async function toAgentAttachment(file: PromptInputMessage["files"][number]) {
  const maybeFileId = (file as unknown as { id?: unknown }).id;
  const content = await readAttachmentContent(file);

  return {
    content,
    id: typeof maybeFileId === "string" ? maybeFileId : createId("agent-file"),
    filename: file.filename,
    mediaType: file.mediaType,
    url: file.url,
  } satisfies AgentChatAttachment;
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
  const toolName = `${tool.type} ${tool.title}`.toLowerCase();
  const purpose = isRecord(tool.input) ? tool.input.purpose : "";

  if (toolName.includes("web_fetch") && purpose === "jd") {
    return t.agentToolFetchingJob;
  }

  if (toolName.includes("web_search")) {
    return t.agentToolSearchingJob;
  }

  if (toolName.includes("resume") && toolName.includes("analysis")) {
    return t.agentToolAnalyzingResume;
  }

  if (toolName.includes("material_extract")) {
    return t.agentToolExtractingMaterial;
  }

  if (toolName.includes("edit_plan")) {
    return t.agentToolPlanningEdits;
  }

  if (toolName.includes("edit_execute")) {
    return t.agentToolGeneratingDraft;
  }

  return t.agentToolProcessing;
}

function getToolCompleteLabel(tool: AgentToolInvocation, t: AppMessages) {
  const toolName = `${tool.type} ${tool.title}`.toLowerCase();
  const purpose = isRecord(tool.input) ? tool.input.purpose : "";

  if (toolName.includes("web_fetch") && purpose === "jd") {
    return t.agentToolFetchingJobDone;
  }

  if (toolName.includes("web_search")) {
    return t.agentToolSearchingJobDone;
  }

  if (toolName.includes("resume") && toolName.includes("analysis")) {
    return t.agentToolAnalyzingResumeDone;
  }

  if (toolName.includes("material_extract")) {
    return t.agentToolExtractingMaterialDone;
  }

  if (toolName.includes("edit_plan")) {
    return t.agentToolPlanningEditsDone;
  }

  if (toolName.includes("edit_execute")) {
    return t.agentToolGeneratingDraftDone;
  }

  return t.agentToolProcessingDone;
}

function getToolErrorLabel(tool: AgentToolInvocation, t: AppMessages) {
  const toolName = `${tool.type} ${tool.title}`.toLowerCase();
  const purpose = isRecord(tool.input) ? tool.input.purpose : "";

  if (toolName.includes("web_fetch") && purpose === "jd") {
    return t.agentToolFetchingJobFailed;
  }

  if (toolName.includes("web_search")) {
    return t.agentToolSearchingJobFailed;
  }

  if (toolName.includes("resume") && toolName.includes("analysis")) {
    return t.agentToolAnalyzingResumeFailed;
  }

  if (toolName.includes("material_extract")) {
    return t.agentToolExtractingMaterialFailed;
  }

  if (toolName.includes("edit_plan")) {
    return t.agentToolPlanningEditsFailed;
  }

  if (toolName.includes("edit_execute")) {
    return t.agentToolGeneratingDraftFailed;
  }

  return t.agentToolFailed;
}

function getToolTimelineLabel(tool: AgentToolInvocation, t: AppMessages) {
  if (tool.state === "output-error" || tool.state === "output-denied") {
    return getToolErrorLabel(tool, t);
  }

  if (isToolRunning(tool.state)) {
    return getToolActivityLabel(tool, t);
  }

  return getToolCompleteLabel(tool, t);
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
  onEditTextChange,
  onStartEdit,
  onSubmitEdit,
  t,
}: {
  copied: boolean;
  disabled: boolean;
  editedText: string;
  isEditing: boolean;
  message: AgentPanelMessage;
  onCancelEdit: () => void;
  onCopy: () => void;
  onEditTextChange: (value: string) => void;
  onStartEdit: () => void;
  onSubmitEdit: () => void;
  t: AppMessages;
}) {
  const submitDisabled = disabled || !editedText.trim();

  return (
    <div
      className={cn(
        "group/user-message flex max-w-full flex-col items-end",
        isEditing && "w-full",
      )}
    >
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

                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
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
                className="h-6 rounded-md px-2 text-xs text-muted-foreground hover:bg-[#f5f5f6] hover:text-foreground"
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

        {message.files?.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {message.files.map((file) => (
              <span
                key={file.id ?? file.url ?? file.filename}
                className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-primary-foreground/20 bg-primary-foreground/10 px-2.5 py-1 text-xs"
              >
                <FileText className="size-3" />
                <span className="truncate">
                  {file.filename || "Attachment"}
                </span>
              </span>
            ))}
          </div>
        ) : null}
      </MessageContent>

      {!isEditing ? (
        <MessageActions className="pointer-events-none mr-1 mt-0.5 h-5 justify-end gap-1 opacity-0 transition-opacity duration-150 group-hover/user-message:pointer-events-auto group-hover/user-message:opacity-100 group-focus-within/user-message:pointer-events-auto group-focus-within/user-message:opacity-100">
          <MessageAction
            tooltip={copied ? t.agentCopiedMessage : t.agentCopyMessage}
            label={copied ? t.agentCopiedMessage : t.agentCopyMessage}
            variant="ghost"
            size="icon-xs"
            className="size-5 rounded-md text-muted-foreground transition-[background-color,box-shadow,color] hover:bg-[#f5f5f6] hover:text-foreground hover:shadow-[0_2px_8px_rgba(15,23,42,0.10)] focus-visible:bg-[#f5f5f6] focus-visible:text-foreground focus-visible:shadow-[0_2px_8px_rgba(15,23,42,0.10)]"
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
            className="size-5 rounded-md text-muted-foreground transition-[background-color,box-shadow,color] hover:bg-[#f5f5f6] hover:text-foreground hover:shadow-[0_2px_8px_rgba(15,23,42,0.10)] focus-visible:bg-[#f5f5f6] focus-visible:text-foreground focus-visible:shadow-[0_2px_8px_rgba(15,23,42,0.10)]"
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

function formatCountMessage(template: string, count: number) {
  return template.replace("{count}", String(count));
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
    if (tool.title !== "edit_execute" || !isRecord(tool.output)) {
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
  const [isOpen, setIsOpen] = useState(false);

  if (completedTools.length === 0) {
    return null;
  }

  return (
    <div className="text-xs">
      <button
        aria-expanded={isOpen}
        className="group/details flex w-fit max-w-full cursor-pointer items-center gap-1.5 rounded-md px-1 py-0.5 font-medium leading-5 text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        type="button"
        onClick={() => {
          setIsOpen((open) => !open);
        }}
      >
        <SquareTerminal className="size-3.5 transition-colors duration-200" />
        <span>
          {formatCountMessage(t.agentToolDetailsComplete, completedTools.length)}
        </span>
        <ChevronRight
          className={cn(
            "size-3.5 opacity-0 transition-[opacity,transform] duration-200 group-hover/details:opacity-100 group-focus-visible/details:opacity-100",
            isOpen && "rotate-90 opacity-100",
          )}
        />
      </button>
      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity,transform] duration-200 ease-out",
          isOpen
            ? "grid-rows-[1fr] translate-y-0 opacity-100"
            : "pointer-events-none grid-rows-[0fr] -translate-y-1 opacity-0",
        )}
      >
        <div className="overflow-hidden">
          <div className="mt-1 space-y-1 pl-6 text-xs leading-5 text-muted-foreground">
            {completedTools.map((tool) => (
              <p key={`${tool.id}-${tool.state}`} className="break-words">
                {getToolTimelineLabel(tool, t)}
              </p>
            ))}
          </div>
        </div>
      </div>
    </div>
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
  hasAgentDraft,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  shouldShowDraftActions,
  t,
}: {
  edits: AgentResumeEditSuggestion[];
  observations: Map<string, { before?: string; after?: string }>;
  hasAgentDraft: boolean;
  onApplyAgentDraft: () => void;
  onDiscardAgentDraft: () => void;
  shouldShowDraftActions: boolean;
  t: AppMessages;
}) {
  if (edits.length === 0) {
    return null;
  }

  return (
    <div className="mt-4 rounded-2xl border border-border/70 bg-muted/25 p-3">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        <ClipboardList className="size-3.5" />
        {t.agentChangeSummaryTitle}
      </div>
      <p className="mt-2 text-sm font-medium text-foreground">
        {formatCountMessage(t.agentReviewReady, edits.length)}
      </p>
      {hasAgentDraft ? (
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {t.agentDraftSynced}
        </p>
      ) : null}
      <div className="mt-3 space-y-1.5 text-xs leading-5 text-muted-foreground">
        {edits.slice(0, 4).map((edit) => {
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
  agentSettings,
  onSelectedModelChange,
  hasAgentDraft,
  agentDraftState,
  onPreviewAgentEdits,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  onOpenModelSettings,
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
  agentSettings: AgentSettings;
  onSelectedModelChange: (modelId: string) => void;
  hasAgentDraft: boolean;
  agentDraftState: AgentDraftState | null;
  onPreviewAgentEdits: (
    edits: AgentResumeEditSuggestion[],
    baseResume: ResumeData,
    sourceMessageId?: string,
  ) => void;
  onApplyAgentDraft: () => void;
  onDiscardAgentDraft: () => void;
  onOpenModelSettings: () => void;
}) {
  const [messages, setMessages] = useState<AgentPanelMessage[]>([]);
  const [streamingMessage, setStreamingMessage] =
    useState<AgentPanelMessage | null>(null);
  const [isResponding, setIsResponding] = useState(false);
  const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingMessageText, setEditingMessageText] = useState("");
  const replyTimerRef = useRef<number | null>(null);
  const copyTimerRef = useRef<number | null>(null);
  const activeRequestAbortRef = useRef<AbortController | null>(null);
  const streamingMessageRef = useRef<AgentPanelMessage | null>(null);
  const previewedEditsKeyRef = useRef<string | null>(null);
  const requestResumeRef = useRef<ResumeData>(resume);
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
    () => (streamingMessage ? [...messages, streamingMessage] : messages),
    [messages, streamingMessage],
  );
  const latestDraftMessageId = useMemo(() => {
    for (let index = visibleMessages.length - 1; index >= 0; index -= 1) {
      const message = visibleMessages[index];

      if (message.response?.edits?.length) {
        return message.id;
      }
    }

    return null;
  }, [visibleMessages]);
  const hasConfiguredModel = Boolean(selectedModel);

  useEffect(() => {
    let cancelled = false;

    activeRequestAbortRef.current?.abort();
    activeRequestAbortRef.current = null;

    if (replyTimerRef.current) {
      window.clearTimeout(replyTimerRef.current);
      replyTimerRef.current = null;
    }

    setMessages([]);
    setStreamingMessage(null);
    setIsResponding(false);
    setCopiedMessageId(null);
    setEditingMessageId(null);
    setEditingMessageText("");

    if (!resumeId) {
      return () => {
        cancelled = true;
      };
    }

    void loadAgentSession(resumeId)
      .then((session) => {
        if (!cancelled) {
          setMessages(
            session.messages.map((message) =>
              toPanelMessage(message, ALL_AGENT_TRANSIENT_MODEL_STATUS_TEXTS),
            ),
          );
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Failed to load agent session.", error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [resumeId]);

  useEffect(() => {
    streamingMessageRef.current = streamingMessage;
  }, [streamingMessage]);

  useEffect(() => {
    return () => {
      if (replyTimerRef.current) {
        window.clearTimeout(replyTimerRef.current);
      }
      if (copyTimerRef.current) {
        window.clearTimeout(copyTimerRef.current);
      }
      activeRequestAbortRef.current?.abort();
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

  function submitPrompt(message: PromptInputMessage) {
    if (!hasConfiguredModel) {
      toast.info(t.agentModelRequiredHint, {
        closeButton: true,
      });
      return;
    }

    void (async () => {
      const files = await Promise.all(message.files.map(toAgentAttachment));
      await sendPrompt(message.text, files);
    })();
  }

  function syncPreviewEdits(
    edits: AgentResumeEditSuggestion[] | undefined,
    sourceMessageId?: string,
  ) {
    if (!edits?.length) {
      return;
    }

    const key = getEditsPreviewKey(edits);

    if (previewedEditsKeyRef.current === key) {
      return;
    }

    previewedEditsKeyRef.current = key;
    onPreviewAgentEdits(edits, requestResumeRef.current, sourceMessageId);
  }

  const stopResponding = useCallback(() => {
    if (replyTimerRef.current) {
      window.clearTimeout(replyTimerRef.current);
      replyTimerRef.current = null;
    }

    activeRequestAbortRef.current?.abort();
    activeRequestAbortRef.current = null;

    const partialMessage = streamingMessageRef.current;
    if (partialMessage && hasAssistantRenderableContent(partialMessage)) {
      setMessages((currentMessages) => {
        if (currentMessages.some((message) => message.id === partialMessage.id)) {
          return currentMessages;
        }

        return [...currentMessages, partialMessage];
      });
    }

    setStreamingMessage(null);
    setIsResponding(false);
  }, []);

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

  async function sendPrompt(
    text: string,
    files: AgentChatAttachment[] = [],
    options: {
      baseMessages?: AgentPanelMessage[];
      messageId?: string;
      replaceSessionBeforeSend?: boolean;
    } = {},
  ) {
    const prompt = text.trim();
    const attachmentSummary = files
      .map((file) => file.filename || file.url || "Attachment")
      .filter(Boolean)
      .join(", ");
    const visiblePrompt = prompt || attachmentSummary;

    if ((!prompt && files.length === 0) || isResponding) {
      return;
    }

    const baseMessages = options.baseMessages ?? messages;
    const looksLikeJobBrief = isLikelyJobBriefPrompt(prompt);
    const nextJobBrief = looksLikeJobBrief ? prompt : jobBrief;
    const nextKeywordMatch = looksLikeJobBrief
      ? getKeywordMatch(resume, nextJobBrief, 0, t)
      : keywordMatch;
    const userMessage: AgentPanelMessage = {
      files,
      id: options.messageId ?? createId("agent-user"),
      role: "user",
      text: visiblePrompt,
    };
    const nextMessages = [...baseMessages, userMessage];
    const apiMessages = nextMessages.map(toConversationMessage);

    setIsResponding(true);
    setMessages(nextMessages);
    setStreamingMessage(null);
    previewedEditsKeyRef.current = null;
    requestResumeRef.current = resume;

    if (looksLikeJobBrief) {
      onJobBriefChange(prompt);
    }

    if (replyTimerRef.current) {
      window.clearTimeout(replyTimerRef.current);
    }

    if (options.replaceSessionBeforeSend && resumeId) {
      try {
        await replaceAgentSession(resumeId, {
          locale,
          messages: apiMessages,
        });
      } catch (error) {
        console.warn(
          "Failed to replace agent session before editing; continuing with chat request.",
          error,
        );
      }
    }

    replyTimerRef.current = window.setTimeout(() => {
      void (async () => {
        replyTimerRef.current = null;
        const abortController = new AbortController();
        activeRequestAbortRef.current = abortController;

        try {
          const response = await sendAgentChatMessage(
            {
              appliedActions: [],
              conversation: apiMessages,
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
              settings: agentSettings,
              stream: true,
            },
            {
              onMessage: (streamedMessage) => {
                if (abortController.signal.aborted) {
                  return;
                }

                const panelMessage = toAssistantPanelMessage(
                  streamedMessage,
                  t.agentTransientModelStatusTexts,
                );

                syncPreviewEdits(panelMessage.response?.edits, panelMessage.id);
                setStreamingMessage(panelMessage);
              },
              signal: abortController.signal,
            },
          );

          if (abortController.signal.aborted) {
            return;
          }

          syncPreviewEdits(response.message.edits, response.message.id);
          setMessages([
            ...nextMessages,
            toAssistantPanelMessage(
              response.message,
              t.agentTransientModelStatusTexts,
            ),
          ]);
        } catch (error) {
          if (isAbortError(error)) {
            return;
          }

          console.error("Failed to send agent chat message.", error);
          if (!isApiErrorToastShown(error)) {
            toast.error(t.agentRequestFailed, {
              closeButton: true,
            });
          }
        } finally {
          if (activeRequestAbortRef.current === abortController) {
            activeRequestAbortRef.current = null;
          }
          setIsResponding(false);
          setStreamingMessage(null);
          replyTimerRef.current = null;
        }
      })();
    }, AGENT_REQUEST_DEBOUNCE_MS);
  }

  return (
    <TooltipProvider>
      <aside
        data-mode={mode}
        className={cn(
          "agent-panel-card flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-sm transition-all duration-300 print:hidden",
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
            <div className="relative flex min-h-0 flex-1 flex-col">
              <Conversation
                className="min-h-0 min-w-0 flex-1 overflow-x-hidden"
              >
                <ConversationContent
                  scrollClassName="agent-thread-scroll"
                  className={cn(
                    "agent-thread-content-mask min-w-0 overflow-x-hidden px-3 pb-[132px]",
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
                          {t.agentEmptyPrompt}
                        </p>
                        {!hasConfiguredModel ? (
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
                        message.id === latestDraftMessageId &&
                        Boolean(response?.edits?.length) &&
                        hasAgentDraft &&
                        !isResponding;
                      const shouldShowChangeSummary =
                        Boolean(response?.edits?.length) &&
                        !isStreamingAssistant;
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
                              onEditTextChange={setEditingMessageText}
                              onStartEdit={() => startEditingUserMessage(message)}
                              onSubmitEdit={() => {
                                void submitEditedUserMessage(message);
                              }}
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
                <ConversationScrollButton className="bottom-[132px] z-20" />
              </Conversation>
              <section className="pointer-events-none absolute inset-x-0 bottom-0 z-10 px-3 pb-3">
                <div aria-hidden="true" className="absolute bottom-0 left-0 right-3 h-8 bg-card" />
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
                        multiple
                        onSubmit={submitPrompt}
                        className={cn(
                          "p-0 text-foreground [&_[data-slot=input-group]]:overflow-hidden [&_[data-slot=input-group]]:rounded-[26px] [&_[data-slot=input-group]]:border-border/70 [&_[data-slot=input-group]]:bg-background [&_[data-slot=input-group]]:shadow-sm",
                          !hasConfiguredModel &&
                            "[&_[data-slot=input-group]]:cursor-not-allowed",
                        )}
                      >
                        <AgentPromptAttachmentsDisplay />
                        <PromptInputBody className="px-4 pt-3">
                          <PromptInputTextarea
                            rows={1}
                            disabled={!hasConfiguredModel}
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
                              disabled={!hasConfiguredModel}
                              label={t.agentAddAttachments}
                            />

                            <ModelSelector
                              open={modelSelectorOpen}
                              onOpenChange={setModelSelectorOpen}
                            >
                              <ModelSelectorTrigger asChild>
                                <PromptInputButton
                                  size="sm"
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

                          <PromptInputSubmit
                            status={isResponding ? "streaming" : "ready"}
                            disabled={!hasConfiguredModel}
                            onStop={stopResponding}
                            className="ml-3 h-8 min-w-10 shrink-0 rounded-[14px] bg-foreground px-3 text-background shadow-none transition-none hover:!bg-foreground hover:!text-background disabled:cursor-not-allowed"
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
