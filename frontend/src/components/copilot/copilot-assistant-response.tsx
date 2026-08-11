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
  getAgentCitationSourceIds,
  hasAgentCitationMarkupCandidate,
  hasCompleteAgentCitationMarkup,
  isPlainAgentText,
  stripAgentCitationMarkup,
} from "@/lib/agent-message-rendering";
import type { AgentSource } from "@/types/api";
import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import type { Components } from "streamdown";

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

type CitableAgentSource = AgentSource & { url: string };

const EMPTY_CITATION_SOURCES = new Map<string, CitableAgentSource>();
const AgentCitationSourcesContext =
  createContext<ReadonlyMap<string, CitableAgentSource>>(
    EMPTY_CITATION_SOURCES,
  );
const AGENT_CITATION_TAGS = { citation: ["source_ids"] };
const AGENT_LITERAL_TAGS = ["citation"];

function AgentInlineCitationCard({
  sources,
}: {
  sources: CitableAgentSource[];
}) {
  const triggerSources = sources.map((source) => source.url);

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
            {sources.map((source) => (
              <InlineCitationCarouselItem key={source.id}>
                <InlineCitationSource
                  description={source.excerpt}
                  title={source.title}
                  url={source.url}
                />
              </InlineCitationCarouselItem>
            ))}
          </InlineCitationCarouselContent>
        </InlineCitationCarousel>
      </InlineCitationCardBody>
    </InlineCitationCard>
  );
}

function AgentCitationTag({
  children,
  source_ids: sourceIdsValue,
}: Record<string, unknown> & { children?: ReactNode }) {
  const sourceById = useContext(AgentCitationSourcesContext);
  const sourceIds = getAgentCitationSourceIds(sourceIdsValue);
  const sources = sourceIds.flatMap((sourceId) => {
    const source = sourceById.get(sourceId);
    return source ? [source] : [];
  });

  if (!sources.length || sources.length !== sourceIds.length) {
    return <>{children}</>;
  }

  return (
    <InlineCitation>
      <InlineCitationText>{children}</InlineCitationText>
      <AgentInlineCitationCard sources={sources} />
    </InlineCitation>
  );
}

const AGENT_CITATION_COMPONENTS: Components = {
  citation: AgentCitationTag,
};

function getCitableSourceMap(sources: AgentSource[] | undefined) {
  const sourceById = new Map<string, CitableAgentSource>();

  for (const source of sources ?? []) {
    if (source.sourceType !== "web") {
      continue;
    }

    const url = getValidSourceUrl(source);
    if (url) {
      sourceById.set(source.id, { ...source, url });
    }
  }

  return sourceById;
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

/**
 * Owns the complete assistant-text rendering policy: edit-table cleanup,
 * lightweight plain text, optional rich Markdown, and source placement.
 */
export function AgentAssistantResponse({
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
  const sourceById = useMemo(() => getCitableSourceMap(sources), [sources]);

  if (!responseText.trim()) {
    return null;
  }

  if (hasAgentCitationMarkupCandidate(responseText)) {
    if (!hasCompleteAgentCitationMarkup(responseText)) {
      const safeText = stripAgentCitationMarkup(responseText);
      return isPlainAgentText(safeText) ? (
        <AgentPlainResponse text={safeText} />
      ) : (
        <AgentRichResponse text={safeText} />
      );
    }

    return (
      <AgentCitationSourcesContext.Provider value={sourceById}>
        <AgentRichResponse
          allowedTags={AGENT_CITATION_TAGS}
          components={AGENT_CITATION_COMPONENTS}
          fallbackText={stripAgentCitationMarkup(responseText)}
          literalTagContent={AGENT_LITERAL_TAGS}
          text={responseText}
        />
      </AgentCitationSourcesContext.Provider>
    );
  }

  if (isPlainAgentText(responseText)) {
    return <AgentPlainResponse text={responseText} />;
  }

  return <AgentRichResponse text={responseText} />;
}
