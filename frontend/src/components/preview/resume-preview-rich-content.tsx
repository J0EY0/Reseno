import { lazy, Suspense, useMemo } from "react";

import { getRenderableFieldDiffs } from "@/components/preview/resume-preview-diffs";
import { isRichTextEmpty, sanitizeRichTextHtml } from "@/lib/rich-text";
import { cn } from "@/lib/utils";

type FieldDiffs = ReturnType<typeof getRenderableFieldDiffs>;

const PreciseRichHighlights = lazy(() =>
  import("@/components/preview/resume-preview-rich-diff").then(
    ({ RichHighlights: component }) => ({ default: component }),
  ),
);
const PreciseRichListDiff = lazy(() =>
  import("@/components/preview/resume-preview-rich-diff").then(
    ({ RichListDiff: component }) => ({ default: component }),
  ),
);

function HighlightsFallback({
  diffs,
  highlights,
}: {
  diffs: FieldDiffs;
  highlights: string[];
}) {
  const visibleHighlights = useMemo(
    () =>
      highlights
        .filter((value) => !isRichTextEmpty(value))
        .map((value) => sanitizeRichTextHtml(value)),
    [highlights],
  );
  const hasDiffs = diffs.length > 0;
  const className = cn(
    hasDiffs && "resume-diff-field resume-diff-field--whole",
  );
  const diffPath = diffs.map((diff) => diff.path).join(" ");
  if (visibleHighlights.length === 1) {
    return (
      <div
        className={className}
        data-resume-diff-path={hasDiffs ? diffPath : undefined}
        dangerouslySetInnerHTML={{
          __html: visibleHighlights[0],
        }}
      />
    );
  }
  return (
    <ul
      className={className}
      data-resume-diff-path={hasDiffs ? diffPath : undefined}
    >
      {visibleHighlights.map((value, index) => (
        <li
          dangerouslySetInnerHTML={{ __html: value }}
          key={`${index}-${value}`}
        />
      ))}
    </ul>
  );
}

export function RichHighlights(props: {
  diffs: FieldDiffs;
  highlights: string[];
}) {
  const fallback = <HighlightsFallback {...props} />;
  return props.diffs.length === 0 ? (
    fallback
  ) : (
    <Suspense fallback={fallback}>
      <PreciseRichHighlights {...props} />
    </Suspense>
  );
}

export function RichListDiff({
  diffs,
  html,
}: {
  diffs: FieldDiffs;
  html: string;
}) {
  const hasDiffs = diffs.length > 0;
  const sanitized = useMemo(() => sanitizeRichTextHtml(html), [html]);
  const fallback = (
    <div
      className={cn(hasDiffs && "resume-diff-field resume-diff-field--whole")}
      data-resume-diff-path={
        hasDiffs ? diffs.map((diff) => diff.path).join(" ") : undefined
      }
      dangerouslySetInnerHTML={{ __html: sanitized }}
    />
  );
  return diffs.length === 0 ? (
    fallback
  ) : (
    <Suspense fallback={fallback}>
      <PreciseRichListDiff diffs={diffs} html={html} />
    </Suspense>
  );
}
