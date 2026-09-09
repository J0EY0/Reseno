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
} from "@/components/ai-elements/inline-citation";
import {
  createAgentMarkdownComponents,
  getAgentMarkdownFallbackText,
} from "@/lib/agent-markdown-presentation";
import { isPlainAgentText } from "@/lib/agent-message-rendering";
import type { AgentSource } from "@/types/api";
import type { AppMessages } from "@/i18n";
import { useMemo } from "react";

import {
  AgentPlainResponse,
  AgentRichResponse,
} from "./copilot-response-content";

function getValidSourceUrl(source: AgentSource) {
  if (!source.url) {
    return null;
  }

  try {
    const url = new URL(source.url);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

type AgentWebSource = AgentSource & { url: string };

function AgentSourcesCitation({
  sources,
  t,
}: {
  sources: AgentWebSource[];
  t: AppMessages;
}) {
  if (!sources.length) {
    return null;
  }

  const sourceUrls = sources.map((source) => source.url);

  return (
    <InlineCitation>
      <InlineCitationCard>
        <InlineCitationCardTrigger sources={sourceUrls} />
        <InlineCitationCardBody>
          <InlineCitationCarousel>
            <InlineCitationCarouselHeader>
              <InlineCitationCarouselPrev aria-label={t.agentPreviousSource} />
              <InlineCitationCarouselNext aria-label={t.agentNextSource} />
              <InlineCitationCarouselIndex />
            </InlineCitationCarouselHeader>
            <InlineCitationCarouselContent>
              {sources.map((source) => (
                <InlineCitationCarouselItem key={source.url}>
                  <InlineCitationSource
                    copyLabel={t.agentCopySourceLink}
                    title={source.title || source.url}
                    url={source.url}
                  />
                </InlineCitationCarouselItem>
              ))}
            </InlineCitationCarouselContent>
          </InlineCitationCarousel>
        </InlineCitationCardBody>
      </InlineCitationCard>
    </InlineCitation>
  );
}

function getWebSources(sources: AgentSource[] | undefined) {
  const sourceByUrl = new Map<string, AgentWebSource>();

  for (const source of sources ?? []) {
    if (source.sourceType !== "web") {
      continue;
    }

    const url = getValidSourceUrl(source);
    if (url && !sourceByUrl.has(url)) {
      sourceByUrl.set(url, { ...source, url });
    }
  }

  return [...sourceByUrl.values()];
}

/**
 * Owns the complete assistant-text rendering policy: lightweight plain text,
 * optional rich Markdown, and source placement.
 */
export function AgentAssistantResponse({
  fieldLabels,
  isStreaming = false,
  sources,
  t,
  text,
}: {
  fieldLabels?: ReadonlyMap<string, string>;
  isStreaming?: boolean;
  sources: AgentSource[] | undefined;
  t: AppMessages;
  text: string;
}) {
  const webSources = useMemo(() => getWebSources(sources), [sources]);
  const markdownComponents = useMemo(
    () =>
      fieldLabels?.size
        ? createAgentMarkdownComponents(fieldLabels)
        : undefined,
    [fieldLabels],
  );
  const fallbackText = useMemo(
    () =>
      fieldLabels?.size
        ? getAgentMarkdownFallbackText(text, fieldLabels)
        : text,
    [fieldLabels, text],
  );
  const hasWebSources = webSources.length > 0;
  const shouldUseRichResponse = isStreaming || !isPlainAgentText(text);

  if (!text.trim()) {
    return null;
  }

  return (
    <div>
      {shouldUseRichResponse ? (
        <AgentRichResponse
          text={text}
          components={markdownComponents}
          fallbackText={fallbackText}
          inlineTail={hasWebSources}
          isStreaming={isStreaming}
        />
      ) : (
        <AgentPlainResponse inlineTail={hasWebSources} text={text} />
      )}
      {hasWebSources ? (
        <>
          {" "}
          <AgentSourcesCitation sources={webSources} t={t} />
        </>
      ) : null}
    </div>
  );
}
