import { Fragment } from "react";

import { createInlineDiffParts } from "@/components/preview/resume-preview-diff-algorithms";
import { cn } from "@/lib/utils";
import type { ResumeDraftDiff } from "@/types/resume";

function displayValue(value: unknown) {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value) && value.every((entry) => typeof entry === "string")) {
    return value.join(" · ");
  }
  return null;
}

export function PreciseResumeDiffText({
  className,
  diffs,
  value,
}: {
  className?: string;
  diffs: ResumeDraftDiff[];
  value: string;
}) {
  const diff = diffs.at(-1)!;
  const before = displayValue(diffs[0].before);
  const after = displayValue(diff.after);
  const canShowInlineChange =
    diffs.length === 1 && before !== null && after === value;

  if (value.length === 0 && canShowInlineChange) {
    return (
      <span
        className={className}
        data-resume-diff-path={diffs.map((entry) => entry.path).join(" ")}
      />
    );
  }
  const parts = canShowInlineChange
    ? createInlineDiffParts(before, value)
    : [{ changed: false, value }];
  const hasVisibleInlineChange = parts.some((part) => part.changed);

  return (
    <span
      className={cn(
        "resume-diff-field",
        hasVisibleInlineChange
          ? "resume-diff-field--inline"
          : "resume-diff-field--whole",
        className,
      )}
      data-resume-diff-path={diffs.map((entry) => entry.path).join(" ")}
    >
      {parts.map((part, index) => {
        return (
          <Fragment key={`${index}-${part.value}`}>
            {part.changed ? (
              <mark
                className="resume-diff-inline"
                data-resume-diff-fragment="added"
              >
                {part.value}
              </mark>
            ) : (
              part.value
            )}
          </Fragment>
        );
      })}
    </span>
  );
}
