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
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
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
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
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
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool";
import { Button } from "@/components/ui/button";
import {
  BookOpen,
  Bot,
  Check,
  ClipboardList,
  FileText,
  RotateCcw,
  WandSparkles,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import type { AppMessages, Locale } from "@/i18n";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { loadAgentSession, sendAgentChatMessage } from "@/lib/agent-api";
import {
  getModelProviderMeta,
  inferModelProviderId,
} from "@/lib/model-providers";
import { isApiErrorToastShown } from "@/lib/api-client";
import { createId, getKeywordMatch } from "@/lib/resume";
import { cn } from "@/lib/utils";
import type {
  AgentChatAttachment,
  AgentChatMessage,
  AgentConversationMessage,
  AgentResumeEditSuggestion,
  AgentSource,
  AgentStoredMessage,
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
const TEXT_ATTACHMENT_PATTERN =
  /^(text\/|application\/json|application\/xml|application\/.*\+json)/i;
const TRANSIENT_MODEL_STATUS_TEXT = new Set([
  "正在等待模型返回。",
  "Waiting for the model response.",
  "我先分析目标岗位和当前简历，然后再给出可执行建议。",
  "I will analyze the target role and current resume first, then return actionable suggestions.",
]);

interface AgentPanelMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  files?: AgentChatAttachment[];
  response?: AgentChatMessage;
}

function getModelProvider(config: ModelConfig) {
  const provider = getModelProviderMeta(inferModelProviderId(config));

  return { id: provider.iconProvider, label: provider.label };
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

function isLikelyJobBriefPrompt(prompt: string) {
  const trimmed = prompt.trim();

  return (
    trimmed.length >= 140 ||
    trimmed.split(/\n+/).filter(Boolean).length >= 3 ||
    /(岗位|jd|职责|任职|要求|job description|responsibilities|requirements|qualifications)/i.test(
      trimmed,
    )
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
    role: message.role,
    text: message.text,
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

function stripTransientModelStatus(text: string) {
  const trimmed = text.trim();

  return TRANSIENT_MODEL_STATUS_TEXT.has(trimmed) ? "" : text;
}

function sanitizeAgentResponse(message: AgentChatMessage): AgentChatMessage {
  return {
    ...message,
    text: stripTransientModelStatus(message.text),
    sources: message.sources?.filter(isCitationSource),
  };
}

function toAssistantPanelMessage(message: AgentChatMessage): AgentPanelMessage {
  const response = sanitizeAgentResponse(message);

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

function isPlainAgentText(text: string) {
  return !/(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>|```)|[`|[\]]/.test(text);
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
  sources,
  text,
}: {
  sources: AgentSource[] | undefined;
  text: string;
}) {
  if (!sources?.some((source) => getValidSourceUrl(source))) {
    return <MessageResponse>{text}</MessageResponse>;
  }

  if (!isPlainAgentText(text)) {
    return (
      <>
        <MessageResponse>{text}</MessageResponse>
        <span className="mt-1 inline-block text-sm leading-relaxed">
          <InlineCitation>
            <AgentInlineCitationCard sources={sources} />
          </InlineCitation>
        </span>
      </>
    );
  }

  const { citationText, prefix, trailingWhitespace } =
    splitTrailingCitationText(text);

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

function toPanelMessage(message: AgentStoredMessage): AgentPanelMessage {
  const messageId = message.id ?? createId("agent-stored");
  const text = stripTransientModelStatus(message.text);
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
      ? sanitizeAgentResponse(message.response)
      : fallbackResponse,
  };
}

function formatToolOutput(output: AgentToolInvocation["output"]) {
  if (typeof output === "string") {
    return output;
  }

  if (output === undefined || output === null) {
    return "";
  }

  try {
    return JSON.stringify(output, null, 2);
  } catch {
    return String(output);
  }
}

function isToolRunning(state: AgentToolInvocation["state"]) {
  return (
    state === "approval-requested" ||
    state === "input-available" ||
    state === "input-streaming"
  );
}

function hasAssistantRenderableContent(message: AgentPanelMessage) {
  const response = message.response;

  return Boolean(
    message.text.trim() ||
      response?.reasoning?.trim() ||
      response?.tools?.length ||
      response?.suggestions?.length ||
      response?.edits?.length ||
      response?.knowledge?.length ||
      response?.sources?.length ||
      response?.quickReplies?.length,
  );
}

function getRunningToolLabel(
  tools: AgentToolInvocation[] | undefined,
  t: AppMessages,
) {
  const runningTool = tools?.find((tool) => isToolRunning(tool.state));

  if (!runningTool) {
    return null;
  }

  const toolName = `${runningTool.type} ${runningTool.title}`.toLowerCase();

  if (toolName.includes("resume") && toolName.includes("analysis")) {
    return t.agentToolAnalyzingResume;
  }

  return t.agentToolRunning;
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
        "flex min-w-0 items-center text-xs font-medium",
        className,
      )}
      role="status"
    >
      <Shimmer
        as="span"
        className="max-w-full truncate text-muted-foreground"
        duration={1.6}
        spread={1.6}
      >
        {label}
      </Shimmer>
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
  onPreviewAgentEdits: (edits: AgentResumeEditSuggestion[]) => void;
  onApplyAgentDraft: () => void;
  onDiscardAgentDraft: () => void;
  onOpenModelSettings: () => void;
}) {
  const [messages, setMessages] = useState<AgentPanelMessage[]>([]);
  const [streamingMessage, setStreamingMessage] =
    useState<AgentPanelMessage | null>(null);
  const [isResponding, setIsResponding] = useState(false);
  const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
  const replyTimerRef = useRef<number | null>(null);
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
  const hasConfiguredModel = Boolean(selectedModel);

  useEffect(() => {
    let cancelled = false;

    if (replyTimerRef.current) {
      window.clearTimeout(replyTimerRef.current);
      replyTimerRef.current = null;
    }

    setMessages([]);
    setStreamingMessage(null);
    setIsResponding(false);

    if (!resumeId) {
      return () => {
        cancelled = true;
      };
    }

    void loadAgentSession(resumeId)
      .then((session) => {
        if (!cancelled) {
          setMessages(session.messages.map(toPanelMessage));
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
    return () => {
      if (replyTimerRef.current) {
        window.clearTimeout(replyTimerRef.current);
      }
    };
  }, []);

  const handleModelSelect = useCallback(
    (modelId: string) => {
      onSelectedModelChange(modelId);
      setModelSelectorOpen(false);
    },
    [onSelectedModelChange],
  );

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

  function previewEdits(edits: AgentResumeEditSuggestion[]) {
    if (edits.length === 0) {
      toast.info(t.agentDraftNoChanges, {
        closeButton: true,
      });
      return;
    }

    onPreviewAgentEdits(edits);
  }

  async function sendPrompt(text: string, files: AgentChatAttachment[] = []) {
    const prompt = text.trim();
    const attachmentSummary = files
      .map((file) => file.filename || file.url || "Attachment")
      .filter(Boolean)
      .join(", ");
    const visiblePrompt = prompt || attachmentSummary;

    if ((!prompt && files.length === 0) || isResponding) {
      return;
    }

    const looksLikeJobBrief = isLikelyJobBriefPrompt(prompt);
    const nextJobBrief = looksLikeJobBrief ? prompt : jobBrief;
    const nextKeywordMatch = looksLikeJobBrief
      ? getKeywordMatch(resume, nextJobBrief, 0, t)
      : keywordMatch;
    const userMessage: AgentPanelMessage = {
      files,
      id: createId("agent-user"),
      role: "user",
      text: visiblePrompt,
    };
    const nextMessages = [...messages, userMessage];
    const apiMessages = nextMessages.slice(-12).map(toConversationMessage);

    setIsResponding(true);
    setMessages(nextMessages);
    setStreamingMessage(null);

    if (looksLikeJobBrief) {
      onJobBriefChange(prompt);
    }

    if (replyTimerRef.current) {
      window.clearTimeout(replyTimerRef.current);
    }

    replyTimerRef.current = window.setTimeout(() => {
      void (async () => {
        try {
          const response = await sendAgentChatMessage(
            {
              appliedActions: [],
              conversation: apiMessages.map(({ role, text: itemText }) => ({
                role,
                text: itemText,
              })),
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
              settings: agentSettings,
              stream: true,
            },
            {
              onMessage: (streamedMessage) => {
                setStreamingMessage(toAssistantPanelMessage(streamedMessage));
              },
            },
          );

          setMessages([...nextMessages, toAssistantPanelMessage(response.message)]);
        } catch (error) {
          console.error("Failed to send agent chat message.", error);
          if (!isApiErrorToastShown(error)) {
            toast.error(t.agentRequestFailed, {
              closeButton: true,
            });
          }
        } finally {
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
            ? "xl:self-start"
            : "h-full",
        )}
      >
          <div className="flex items-center gap-3 px-4 py-4">
            <div className="flex size-11 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
              <Bot className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-base font-semibold tracking-tight">{t.aiTitle}</h3>
              {hasAgentDraft ? (
                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                  {t.agentDraftApplyHint}
                </p>
              ) : null}
            </div>
          </div>

          {hasAgentDraft ? (
            <div className="mx-4 mb-3 flex gap-2 rounded-2xl border border-border/70 bg-muted/25 p-2">
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

          <div className="flex min-h-0 flex-1 flex-col">
            <Conversation className="min-h-0 min-w-0 flex-1 overflow-x-hidden">
              <ConversationContent
                className={cn(
                  "min-w-0 overflow-x-hidden px-3 pb-4",
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
                      const reasoningText = response?.reasoning?.trim() ?? "";
                      const runningToolLabel = getRunningToolLabel(
                        response?.tools,
                        t,
                      );
                      const hasRenderableAssistantContent =
                        hasAssistantRenderableContent(message);

                      return (
                        <Message key={message.id} from={message.role}>
                          <MessageContent
                            className={cn(
                              message.role === "user"
                                ? "ml-auto w-fit min-w-8 max-w-full self-end overflow-visible rounded-2xl bg-secondary px-4 py-2.5 text-foreground"
                                : "w-full min-w-0 max-w-full px-0 py-1 text-foreground",
                            )}
                          >
                            {message.role === "user" ? (
                              <span className="block whitespace-pre-wrap break-words leading-relaxed [overflow-wrap:anywhere]">
                                {message.text}
                              </span>
                            ) : (
                              <>
                                {reasoningText ? (
                                  <Reasoning
                                    className="mt-1"
                                    isStreaming={
                                      isStreamingAssistant &&
                                      assistantText.length === 0
                                    }
                                  >
                                    <ReasoningTrigger
                                      getThinkingMessage={(isStreaming, duration) =>
                                        isStreaming
                                          ? t.agentReasoningStreaming
                                          : duration
                                            ? `${t.agentReasoningComplete} ${duration}s`
                                            : t.agentReasoningComplete
                                      }
                                    />
                                    <ReasoningContent>
                                      {reasoningText}
                                    </ReasoningContent>
                                  </Reasoning>
                                ) : null}
                                {response?.tools?.length ? (
                                  <div className="mt-3 space-y-1.5">
                                    <div className="flex min-w-0 items-center justify-between gap-2">
                                      <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                                        {t.agentToolsTitle}
                                      </div>
                                      {runningToolLabel ? (
                                        <AgentToolShimmerStatus
                                          className="shrink-0"
                                          label={runningToolLabel}
                                        />
                                      ) : null}
                                    </div>
                                    {response.tools.map((tool) => {
                                      const toolType = (
                                        tool.type.startsWith("tool-")
                                          ? tool.type
                                          : `tool-${tool.type}`
                                      ) as `tool-${string}`;

                                      return (
                                        <Tool
                                          key={`${tool.id}-${tool.state}`}
                                          defaultOpen={isToolRunning(tool.state)}
                                        >
                                          <ToolHeader
                                            type={toolType}
                                            title={tool.title}
                                            state={tool.state}
                                          />
                                          <ToolContent className="space-y-3 p-2.5">
                                            <ToolInput input={tool.input ?? {}} />
                                            {(tool.output !== undefined ||
                                              tool.errorText) && (
                                              <ToolOutput
                                                errorText={tool.errorText}
                                                output={
                                                  tool.output === undefined
                                                    ? undefined
                                                    : formatToolOutput(tool.output)
                                                }
                                              />
                                            )}
                                          </ToolContent>
                                        </Tool>
                                      );
                                    })}
                                  </div>
                                ) : null}
                                {assistantText ? (
                                  <div className="mt-3">
                                    <AgentAssistantResponse
                                      sources={response?.sources}
                                      text={message.text}
                                    />
                                  </div>
                                ) : isStreamingAssistant &&
                                  !hasRenderableAssistantContent ? (
                                  <AgentTypingDots label={t.agentThinking} />
                                ) : null}
                              </>
                            )}

                            {message.files?.length ? (
                              <div className="mt-3 flex flex-wrap gap-2">
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

                            {response?.suggestions?.length ? (
                              <div className="mt-4 space-y-2">
                                <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                  <WandSparkles className="size-3.5" />
                                  {t.agentSuggestionsTitle}
                                </div>
                                <ul className="mt-2 list-disc space-y-1.5 pl-4 text-sm leading-6 text-muted-foreground">
                                  {response.suggestions.map((suggestion) => (
                                    <li key={suggestion}>{suggestion}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}

                            {response?.edits?.length ? (
                              <div className="mt-4 space-y-2">
                                <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                  <ClipboardList className="size-3.5" />
                                  {t.agentEditsTitle}
                                </div>
                                <div className="space-y-2">
                                  {response.edits.map((edit) => (
                                    <div
                                      key={edit.id}
                                      className="rounded-2xl border border-border/70 bg-background/70 p-3"
                                    >
                                      <p className="text-sm font-medium text-foreground">
                                        {edit.title}
                                      </p>
                                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                        {edit.reason}
                                      </p>
                                      {edit.replacement ? (
                                        <p className="mt-2 rounded-xl bg-muted/45 px-3 py-2 text-xs leading-5 text-foreground">
                                          {edit.replacement}
                                        </p>
                                      ) : null}
                                    </div>
                                  ))}
                                </div>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="secondary"
                                  disabled={isResponding}
                                  className="mt-2 h-8 rounded-xl px-3 text-xs"
                                  onClick={() => previewEdits(response.edits ?? [])}
                                >
                                  <ClipboardList className="mr-1.5 size-3.5" />
                                  {t.agentPreviewEdits}
                                </Button>
                              </div>
                            ) : null}

                            {response?.knowledge?.length ? (
                              <div className="mt-4 space-y-2">
                                <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                  <BookOpen className="size-3.5" />
                                  {t.agentKnowledgeTitle}
                                </div>
                                <ul className="mt-2 space-y-2">
                                  {response.knowledge.map((topic) => (
                                    <li key={`${topic.title}-${topic.detail}`}>
                                      <p className="text-sm font-medium text-foreground">
                                        {topic.title}
                                      </p>
                                      <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
                                        {topic.detail}
                                      </p>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}

                            {response?.quickReplies?.length ? (
                              <div className="mt-4 space-y-2">
                                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                  {t.agentQuickRepliesTitle}
                                </div>
                                <div className="flex flex-wrap gap-2">
                                  {response.quickReplies.map((suggestion) => (
                                    <Button
                                      key={suggestion}
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      disabled={isResponding}
                                      className="h-8 rounded-full px-3 text-xs"
                                      onClick={() => {
                                        void sendPrompt(suggestion);
                                      }}
                                    >
                                      {suggestion}
                                    </Button>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                          </MessageContent>
                        </Message>
                      );
                    })}

                    {isResponding && !streamingMessage ? (
                      <Message from="assistant">
                        <MessageContent className="w-full px-0 py-1 text-muted-foreground">
                          <AgentTypingDots label={t.agentThinking} />
                        </MessageContent>
                      </Message>
                    ) : null}
                  </div>
                )}
              </ConversationContent>
              <ConversationScrollButton />
            </Conversation>

            <section className="px-4 pb-4 pt-3">
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
                        <PromptInputBody className="px-5 pt-4">
                          <PromptInputTextarea
                            rows={1}
                            disabled={!hasConfiguredModel}
                            placeholder={
                              hasConfiguredModel
                                ? t.agentPromptPlaceholderShort
                                : ""
                            }
                            className="min-h-[78px] max-h-[156px] px-5 pb-0 pt-4 text-[15px] leading-[22px] text-foreground placeholder:text-muted-foreground disabled:cursor-not-allowed"
                          />
                        </PromptInputBody>

                        <PromptInputFooter className="justify-between gap-2.5 px-4 pb-3.5 pt-1">
                          <PromptInputTools className="min-w-0 gap-1.5">
                            <PromptInputActionMenu>
                              <PromptInputActionMenuTrigger
                                disabled={!hasConfiguredModel}
                                className="size-8 rounded-[14px] text-foreground transition-none hover:!bg-muted/45 hover:!text-foreground disabled:cursor-not-allowed"
                              />
                              <PromptInputActionMenuContent>
                                <PromptInputActionAddAttachments
                                  label={t.agentAddAttachments}
                                />
                              </PromptInputActionMenuContent>
                            </PromptInputActionMenu>

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
                                  className="h-8 min-w-[72px] max-w-[132px] justify-start text-foreground transition-colors duration-200"
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
                                      "max-w-[76px] truncate text-[12px] font-medium",
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
            </section>
          </div>
      </aside>
    </TooltipProvider>
  );
}
