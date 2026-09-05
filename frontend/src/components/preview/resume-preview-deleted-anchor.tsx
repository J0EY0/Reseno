import { ResumeDiffBadge } from "@/components/preview/resume-preview-diff-badge";
import type { AppMessages } from "@/i18n";
import type { ResumeDraftDiff } from "@/types/resume";

export function ResumeDeletedDiffAnchor({
  diff,
  t,
}: {
  diff: ResumeDraftDiff;
  t: AppMessages;
}) {
  return (
    <div
      className="resume-diff resume-diff--deleted resume-diff-deleted-anchor resume-diff-label-host"
      data-resume-diff-kind={diff.kind}
      data-resume-diff-label={diff.label}
      data-resume-diff-path={diff.path}
    >
      <ResumeDiffBadge diff={diff} t={t} />
      <span className="truncate">{diff.label}</span>
    </div>
  );
}
