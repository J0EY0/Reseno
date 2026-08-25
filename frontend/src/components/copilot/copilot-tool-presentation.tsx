import {
  Message,
  MessageContent,
} from "@/components/ai-elements/message";
import { Shimmer } from "@/components/ai-elements/shimmer";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { AppMessages } from "@/i18n";
import {
  getAgentToolLabelKey,
  getVisibleCompletedTools,
  getVisibleToolIds,
  isToolFailure,
  isToolRunning,
  shouldShowTimelineContinuationStatus,
} from "@/lib/agent-tool-display";
import { cn } from "@/lib/utils";
import type {
  AgentSource,
  AgentTimelinePart,
  AgentToolInvocation,
} from "@/types/api";
import { ChevronRight, SquareTerminal } from "lucide-react";
import { useState } from "react";

import { AgentAssistantResponse } from "./copilot-assistant-response";

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

function formatCountMessage(
  template: string,
  count: number,
  failedCount = 0,
) {
  return template
    .replace("{count}", String(count))
    .replace("{failed}", String(failedCount));
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
      <CollapsibleTrigger className="group/details inline-flex h-auto max-w-full items-center justify-center gap-1.5 rounded-md bg-transparent px-1 py-0.5 text-xs font-medium leading-5 text-muted-foreground shadow-none transition-colors outline-none hover:bg-transparent hover:text-foreground hover:shadow-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
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

/** Renders the interleaved text/tool order emitted by the streaming protocol. */
export function AgentMessageTimeline({
  fieldLabels,
  isStreamingAssistant,
  parts,
  removeMarkdownTables,
  sources,
  tools,
  t,
}: {
  fieldLabels?: ReadonlyMap<string, string>;
  isStreamingAssistant: boolean;
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
  const showContinuationStatus = shouldShowTimelineContinuationStatus(
    visibleParts,
    tools,
    isStreamingAssistant,
  );

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
                fieldLabels={fieldLabels}
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

        return <AgentTimelineToolPart key={part.id} tools={partTools} t={t} />;
      })}
      {showContinuationStatus ? (
        <AgentToolShimmerStatus
          className="text-sm"
          label={t.agentToolContinuing}
        />
      ) : null}
    </div>
  );
}

/** Owns the non-timeline thinking, running-tool, and completed-tool states. */
export function AgentAssistantActivity({
  assistantText,
  hasRenderableAssistantContent,
  isStreamingAssistant,
  tools,
  t,
}: {
  assistantText: string;
  hasRenderableAssistantContent: boolean;
  isStreamingAssistant: boolean;
  tools: AgentToolInvocation[];
  t: AppMessages;
}) {
  const runningTool = tools.find((tool) => isToolRunning(tool.state));
  const runningToolLabel = runningTool
    ? getToolActivityLabel(runningTool, t)
    : null;
  const shouldShowInitialStatus =
    isStreamingAssistant && !assistantText && !tools.length;

  if (runningToolLabel) {
    return (
      <AgentToolShimmerStatus
        className={assistantText ? "mt-3 text-sm" : "text-sm"}
        label={runningToolLabel}
      />
    );
  }

  if (shouldShowInitialStatus) {
    return (
      <AgentToolShimmerStatus
        className={assistantText ? "mt-3 text-sm" : "text-sm"}
        label={t.agentToolThinking}
      />
    );
  }

  if (tools.length) {
    return (
      <div className={assistantText ? "mt-3" : undefined}>
        <AgentToolDetailsDisclosure tools={tools} t={t} />
      </div>
    );
  }

  if (
    !assistantText &&
    isStreamingAssistant &&
    !hasRenderableAssistantContent
  ) {
    return <AgentTypingDots label={t.agentThinking} />;
  }

  return null;
}

export function AgentPendingMessage({ label }: { label: string }) {
  return (
    <Message from="assistant">
      <MessageContent className="w-full px-0 py-1 text-muted-foreground">
        <AgentToolShimmerStatus className="mt-2 text-sm" label={label} />
      </MessageContent>
    </Message>
  );
}
