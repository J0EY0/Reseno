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
import { isPlainAgentText } from "@/lib/agent-message-rendering";
import type { AgentSource } from "@/types/api";

import {
  AgentPlainResponse,
  AgentRichResponse,
} from "./copilot-response-content";

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

  if (!responseText.trim()) {
    return null;
  }

  if (!sources?.some((source) => getValidSourceUrl(source))) {
    if (isPlainAgentText(responseText)) {
      return <AgentPlainResponse text={responseText} />;
    }

    return <AgentRichResponse text={responseText} />;
  }

  if (!isPlainAgentText(responseText)) {
    return (
      <>
        <AgentRichResponse text={responseText} />
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
