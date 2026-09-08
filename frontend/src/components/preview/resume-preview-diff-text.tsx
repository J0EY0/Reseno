import { lazy, Suspense } from "react";

import {
  formatRichTextAsPlainText,
  getInlineTextHtml,
} from "@/lib/rich-text";
import { cn } from "@/lib/utils";
import type { ResumeDraftDiff } from "@/types/resume";

const PreciseResumeDiffText = lazy(() =>
  import("@/components/preview/resume-preview-diff-precision").then(
    ({ PreciseResumeDiffText: component }) => ({ default: component }),
  ),
);

function DiffTextFallback({
  className,
  diffs,
  richText = false,
  value,
}: {
  className?: string;
  diffs: ResumeDraftDiff[];
  richText?: boolean;
  value: string;
}) {
  return (
    <span
      className={cn(
        "resume-diff-field resume-diff-field--whole",
        className,
      )}
      data-resume-diff-path={diffs.map((diff) => diff.path).join(" ")}
    >
      {richText ? (
        <span dangerouslySetInnerHTML={{ __html: getInlineTextHtml(value) }} />
      ) : (
        value
      )}
    </span>
  );
}

export function ResumeDiffText({
  className,
  diffs,
  richText = false,
  value,
}: {
  className?: string;
  diffs: ResumeDraftDiff[];
  richText?: boolean;
  value: string;
}) {
  if (diffs.length === 0) {
    return richText ? (
      <span
        className={className}
        dangerouslySetInnerHTML={{ __html: getInlineTextHtml(value) }}
      />
    ) : (
      <span className={className}>{value}</span>
    );
  }

  if (
    richText &&
    (formatRichTextAsPlainText(value) ||
      diffs.some((diff) =>
        typeof diff.before === "string" && formatRichTextAsPlainText(diff.before),
      ))
  ) {
    return (
      <DiffTextFallback
        className={className}
        diffs={diffs}
        richText
        value={value}
      />
    );
  }

  return (
    <Suspense
      fallback={
        <DiffTextFallback
          className={className}
          diffs={diffs}
          richText={richText}
          value={value}
        />
      }
    >
      <PreciseResumeDiffText
        className={cn(richText && "whitespace-pre-wrap", className)}
        diffs={diffs}
        value={value}
      />
    </Suspense>
  );
}
