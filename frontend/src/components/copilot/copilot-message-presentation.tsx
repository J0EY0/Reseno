import {
  Message,
  MessageContent,
} from "@/components/ai-elements/message";
import type { AppMessages } from "@/i18n";
import { getAgentDisplayFieldLabels } from "@/lib/agent-message-rendering";
import { lazy, memo, Suspense, useMemo } from "react";

import { AgentAssistantResponse } from "./copilot-assistant-response";
import type { AgentPanelMessage } from "./copilot-message-model";
import {
  AgentAssistantActivity,
  AgentMessageTimeline,
} from "./copilot-tool-presentation";

const AgentChangeSummary = lazy(() => import("./copilot-change-summary"));

export { AgentPendingMessage } from "./copilot-tool-presentation";
export { AgentUserMessageRow } from "./copilot-user-message-row";

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

/**
 * The memoized row is the streaming seam: historical assistant messages keep
 * their object identity and can skip work while only the active row changes.
 */
export const AgentAssistantMessageRow = memo(function AgentAssistantMessageRow({
  isStreamingAssistant,
  message,
  t,
}: {
  isStreamingAssistant: boolean;
  message: AgentPanelMessage;
  t: AppMessages;
}) {
  const response = message.response;
  const assistantText = message.text.trim();
  const tools = response?.tools ?? [];
  const timeline = response?.timeline ?? [];
  const shouldRenderTimeline = timeline.length > 0;
  const fieldLabels = useMemo(
    () => getAgentDisplayFieldLabels(response?.edits, t.fieldLabels),
    [response?.edits, t.fieldLabels],
  );

  return (
    <Message from="assistant">
      <MessageContent className="w-full min-w-0 max-w-full px-0 py-1 text-foreground">
        {shouldRenderTimeline ? (
          <AgentMessageTimeline
            fieldLabels={fieldLabels}
            isStreamingAssistant={isStreamingAssistant}
            parts={timeline}
            sources={response?.sources}
            tools={tools}
            t={t}
          />
        ) : (
          <>
            {assistantText ? (
              <div>
                <AgentAssistantResponse
                  fieldLabels={fieldLabels}
                  isStreaming={isStreamingAssistant}
                  sources={response?.sources}
                  text={message.text}
                />
              </div>
            ) : null}
            <AgentAssistantActivity
              assistantText={assistantText}
              hasRenderableAssistantContent={hasAssistantRenderableContent(
                message,
              )}
              isStreamingAssistant={isStreamingAssistant}
              tools={tools}
              t={t}
            />
          </>
        )}
        {response?.edits?.length ? (
          <Suspense fallback={null}>
            <AgentChangeSummary
              response={response}
              t={t}
            />
          </Suspense>
        ) : null}
      </MessageContent>
    </Message>
  );
});
