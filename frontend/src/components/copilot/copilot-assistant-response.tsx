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

function AgentSourcesCitation({ sources }: { sources: AgentWebSource[] }) {
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
              <InlineCitationCarouselPrev />
              <InlineCitationCarouselNext />
              <InlineCitationCarouselIndex />
            </InlineCitationCarouselHeader>
            <InlineCitationCarouselContent>
              {sources.map((source) => (
                <InlineCitationCarouselItem key={source.url}>
                  <InlineCitationSource
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
  sources,
  text,
}: {
  fieldLabels?: ReadonlyMap<string, string>;
  sources: AgentSource[] | undefined;
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

  if (!text.trim()) {
    return null;
  }

  return (
    <div>
      {isPlainAgentText(text) ? (
        <AgentPlainResponse inlineTail={hasWebSources} text={text} />
      ) : (
        <AgentRichResponse
          text={text}
          components={markdownComponents}
          fallbackText={fallbackText}
          inlineTail={hasWebSources}
        />
      )}
      {hasWebSources ? (
        <>
          {" "}
          <AgentSourcesCitation sources={webSources} />
        </>
      ) : null}
    </div>
  );
}
