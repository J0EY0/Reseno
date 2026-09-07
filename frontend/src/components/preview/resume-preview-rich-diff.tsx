import { useMemo } from "react";

import {
  createListDiff,
  type ListDiff,
} from "@/components/preview/resume-preview-diff-algorithms";
import { getRenderableFieldDiffs } from "@/components/preview/resume-preview-diffs";
import {
  isRichTextEmpty,
  sanitizeRichTextHtml,
  stripRichText,
} from "@/lib/rich-text";
import { cn } from "@/lib/utils";

type FieldDiffs = ReturnType<typeof getRenderableFieldDiffs>;

function diffPath(diffs: FieldDiffs) {
  return diffs.map((diff) => diff.path).join(" ");
}

export function RichHighlights({
  diffs,
  highlights,
}: {
  diffs: FieldDiffs;
  highlights: string[];
}) {
  const visibleHighlights = useMemo(
    () => highlights
      .map((value, index) => ({ index, value: sanitizeRichTextHtml(value) }))
      .filter(({ value }) => !isRichTextEmpty(value)),
    [highlights],
  );
  const before = diffs[0]?.before;
  const after = diffs.at(-1)?.after;
  const canDiffItems =
    Array.isArray(before) &&
    Array.isArray(after) &&
    before.every((entry) => typeof entry === "string") &&
    after.every((entry) => typeof entry === "string");
  if (visibleHighlights.length === 0) {
    return null;
  }
  const renderHighlights = (listDiff: ListDiff | null) => {
    const changedIndices = listDiff?.changedIndices ?? null;
    const path = diffPath(diffs);
    const hasPureDeletion = Boolean(
      listDiff &&
        listDiff.hasDeletions &&
        listDiff.changedIndices.size === 0,
    );
    if (visibleHighlights.length === 1) {
      const highlight = visibleHighlights[0];
      const changed =
        (changedIndices?.has(highlight.index) ?? diffs.length > 0) ||
        hasPureDeletion;
      return (
        <div
          className={cn(changed && "resume-diff-field resume-diff-field--whole")}
          data-resume-diff-path={changed ? path : undefined}
        >
          <span
            dangerouslySetInnerHTML={{
              __html: highlight.value,
            }}
          />
        </div>
      );
    }

    const showsFallback =
      (changedIndices === null && diffs.length > 0) || hasPureDeletion;
    return (
      <ul
        className={cn(
          showsFallback && "resume-diff-field resume-diff-field--whole",
        )}
        data-resume-diff-path={showsFallback ? diffPath(diffs) : undefined}
      >
        {visibleHighlights.map(({ index, value }) => {
          const changed = changedIndices?.has(index) ?? false;
          return (
            <li
              className={cn(
                changed && "resume-diff-field resume-diff-field--whole",
              )}
              data-resume-diff-path={changed ? path : undefined}
              key={`${index}-${value}`}
            >
              <span
                dangerouslySetInnerHTML={{
                  __html: value,
                }}
              />
            </li>
          );
        })}
      </ul>
    );
  };

  if (!canDiffItems) {
    return renderHighlights(
      diffs.length > 0
        ? null
        : { changedIndices: new Set<number>(), hasDeletions: false },
    );
  }

  return renderHighlights(createListDiff(before, after));
}

interface ParsedRichList {
  items: string[];
  tag: "ol" | "ul";
}

function parseRichList(html: string): ParsedRichList | null {
  const match = html.match(/^<(ul|ol)>([\s\S]*)<\/\1>$/i);
  if (!match) {
    return null;
  }

  const itemMatches = [...match[2].matchAll(/<li>([\s\S]*?)<\/li>/gi)];
  if (
    itemMatches.length === 0 ||
    itemMatches.map((item) => item[0]).join("") !== match[2]
  ) {
    return null;
  }

  return {
    tag: match[1].toLowerCase() as "ol" | "ul",
    items: itemMatches.map((item) => sanitizeRichTextHtml(item[1])),
  };
}

export function RichListDiff({
  diffs,
  html,
}: {
  diffs: FieldDiffs;
  html: string;
}) {
  const sanitized = useMemo(() => sanitizeRichTextHtml(html), [html]);
  const parsed = useMemo(() => parseRichList(html), [html]);
  const before = diffs[0]?.before;
  const beforeParsed = useMemo(
    () => typeof before === "string" ? parseRichList(before) : null,
    [before],
  );

  if (!parsed && beforeParsed && isRichTextEmpty(sanitized)) {
    return null;
  }

  if (!parsed || !beforeParsed || parsed.tag !== beforeParsed.tag) {
    return (
      <div
        className={cn(
          diffs.length > 0 &&
            "resume-diff-field resume-diff-field--whole",
        )}
        data-resume-diff-path={diffs.length > 0 ? diffPath(diffs) : undefined}
        dangerouslySetInnerHTML={{ __html: sanitized }}
      />
    );
  }

  const List = parsed.tag;
  const renderList = (listDiff: ListDiff | null) => {
    const changedIndices = listDiff?.changedIndices ?? null;
    const path = diffPath(diffs);
    const hasPureDeletion = Boolean(
      listDiff &&
        listDiff.hasDeletions &&
        listDiff.changedIndices.size === 0,
    );
    const showsFallback =
      (changedIndices === null && diffs.length > 0) || hasPureDeletion;
    return (
      <List
        className={cn(
          showsFallback && "resume-diff-field resume-diff-field--whole",
        )}
        data-resume-diff-path={showsFallback ? diffPath(diffs) : undefined}
      >
        {parsed.items.map((item, index) => {
          const changed = changedIndices?.has(index) ?? false;
          return (
            <li
              className={cn(
                changed && "resume-diff-field resume-diff-field--whole",
              )}
              data-resume-diff-path={changed ? path : undefined}
              key={`${index}-${stripRichText(item)}`}
            >
              <span dangerouslySetInnerHTML={{ __html: item }} />
            </li>
          );
        })}
      </List>
    );
  };

  const beforeItems = beforeParsed.items.map(stripRichText);
  const afterItems = parsed.items.map(stripRichText);
  return renderList(createListDiff(beforeItems, afterItems));
}
