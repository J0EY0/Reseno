import { PopoverTitle } from "@/components/ui/popover";
import type { AppMessages } from "@/i18n";
import { formatAgentDiffValue } from "@/lib/agent-diff-value";
import {
  formatRichTextAsPlainText,
  sanitizeRichTextHtml,
} from "@/lib/rich-text";
import { cn } from "@/lib/utils";
import type { ResumeDraftDiff } from "@/types/resume";

function localizedKind(diff: ResumeDraftDiff, t: AppMessages) {
  switch (diff.kind) {
    case "added":
      return t.agentDiffAdded;
    case "deleted":
      return t.agentDiffDeleted;
    case "moved":
      return t.agentDiffMoved;
    case "modified":
      return t.agentDiffModified;
  }
}

function comparisonRows(diff: ResumeDraftDiff, t: AppMessages) {
  const formatPosition = (value: unknown) =>
    typeof value === "number" ? String(value + 1) : formatAgentDiffValue(value);

  switch (diff.kind) {
    case "added":
      return [
        {
          label: t.agentDiffAddedContent,
          value: diff.after,
        },
      ];
    case "deleted":
      return [
        {
          label: t.agentDiffDeletedContent,
          value: diff.before,
        },
      ];
    case "moved":
      return [
        {
          label: t.agentDiffPreviousPosition,
          value: formatPosition(diff.before),
        },
        { label: t.agentDiffNewPosition, value: formatPosition(diff.after) },
      ];
    case "modified":
      return [
        { label: t.agentDiffBefore, value: diff.before },
        { label: t.agentDiffAfter, value: diff.after },
      ];
  }
}

function ComparisonValue({ value }: { value: unknown }) {
  if (typeof value === "string" && formatRichTextAsPlainText(value)) {
    return (
      <div
        className="resume-rich-text"
        dangerouslySetInnerHTML={{ __html: sanitizeRichTextHtml(value) }}
      />
    );
  }
  if (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((item) => typeof item === "string")
  ) {
    return (
      <ul className="list-disc pl-4">
        {value.map((item, index) => (
          <li key={index}>
            <ComparisonValue value={item} />
          </li>
        ))}
      </ul>
    );
  }
  return formatAgentDiffValue(value);
}

export function ResumeDraftReviewComparison({
  diff,
  t,
}: {
  diff: ResumeDraftDiff;
  t: AppMessages;
}) {
  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <PopoverTitle className="min-w-0 break-words text-sm leading-5">
          {diff.label}
        </PopoverTitle>
        <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
          {localizedKind(diff, t)}
        </span>
      </div>
      <dl className="mt-3 grid gap-2">
        {comparisonRows(diff, t).map((row, index) => (
          <div
            className="grid grid-cols-[4.25rem_minmax(0,1fr)] items-start gap-2"
            key={`${row.label}-${index}`}
          >
            <dt className="pt-1 text-[10px] font-medium text-muted-foreground">
              {row.label}
            </dt>
            <dd
              className={cn(
                "max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border bg-card px-2.5 py-1.5 text-xs leading-5 text-card-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                index > 0 || diff.kind === "added"
                  ? "border-success/40"
                  : "border-border",
              )}
              tabIndex={0}
            >
              <ComparisonValue value={row.value} />
            </dd>
          </div>
        ))}
      </dl>
    </>
  );
}
