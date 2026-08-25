import { Button } from "@/components/ui/button";
import type { AppMessages } from "@/i18n";
import {
  compactResumeDraftDiffs,
  getAgentEditDiffFields,
} from "@/lib/agent-diff-value";
import { getAgentQualityWarnings } from "@/lib/agent-panel-state";
import type {
  AgentChatMessage,
  AgentResumeEditSuggestion,
} from "@/types/api";
import type { ResumeDraftDiff } from "@/types/resume";
import { Check, ChevronDown, ClipboardList, RotateCcw } from "lucide-react";

function formatCountMessage(
  template: string,
  count: number,
  failedCount = 0,
) {
  return template
    .replace("{count}", String(count))
    .replace("{failed}", String(failedCount));
}

function getEditSummaryLabel(edit: AgentResumeEditSuggestion) {
  return edit.title.trim() || edit.target.trim() || edit.id;
}

const qualityWarningMessageKeys = {
  inconsistent_item_tense: "agentQualityInconsistentTense",
  mixed_resume_languages: "agentQualityMixedLanguages",
  resume_items_not_reverse_chronological: "agentQualityReverseChronology",
  semantically_duplicate_resume_content: "agentQualityDuplicateContent",
  target_requirements_not_covered: "agentQualityTargetCoverage",
  unsupported_edit_claim: "agentQualityUnsupportedClaim",
} as const satisfies Record<string, keyof AppMessages>;

function getQualityWarningLabel(code: string, t: AppMessages) {
  const messageKey = Object.hasOwn(qualityWarningMessageKeys, code)
    ? qualityWarningMessageKeys[code as keyof typeof qualityWarningMessageKeys]
    : undefined;
  return messageKey ? t[messageKey] : t.agentQualityGeneral;
}

function diffTargetKey(diff: ResumeDraftDiff) {
  return JSON.stringify([
    diff.operationId,
    diff.sectionId ?? "",
    diff.itemId ?? "",
    diff.path,
  ]);
}

/**
 * Owns the edit observation decoding and all draft-review presentation so the
 * message row only decides where the summary belongs.
 */
export function AgentChangeSummary({
  draftDiffs,
  hasAgentDraft,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  response,
  shouldShowDraftActions,
  t,
}: {
  draftDiffs?: ResumeDraftDiff[];
  hasAgentDraft: boolean;
  onApplyAgentDraft: () => void;
  onDiscardAgentDraft: () => void;
  response: AgentChatMessage | undefined;
  shouldShowDraftActions: boolean;
  t: AppMessages;
}) {
  const edits = response?.edits ?? [];

  if (edits.length === 0 || response?.transactionState === "rolled_back") {
    return null;
  }

  const tools = response?.tools ?? [];
  const qualityWarnings = getAgentQualityWarnings(tools);
  const isCommitted = response?.transactionState === "committed";
  const responseDiffs = edits.flatMap((edit) => edit.diffs ?? []);
  const canonicalLabelByTarget = new Map(
    responseDiffs.map((diff) => [diffTargetKey(diff), diff.label]),
  );
  const visibleDiffs = draftDiffs?.map((diff) => ({
    ...diff,
    label: canonicalLabelByTarget.get(diffTargetKey(diff)) ?? diff.label,
  }));
  const compactedDiffs = compactResumeDraftDiffs(
    visibleDiffs ?? responseDiffs,
  );
  const editRows = edits
    .map((edit) => ({
      edit,
      fields: getAgentEditDiffFields(edit, compactedDiffs),
    }))
    .filter((row) => row.fields.length > 0);
  const changeCount = editRows.reduce(
    (count, row) => count + row.fields.length,
    0,
  );

  return (
    <div className="mt-4 rounded-2xl border border-border/70 bg-muted/25 p-3">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        <ClipboardList className="size-3.5" />
        {t.agentChangeSummaryTitle}
      </div>
      {isCommitted ? (
        <p className="mt-2 text-sm font-medium text-foreground">
          {formatCountMessage(t.agentReviewReady, changeCount)}
        </p>
      ) : null}
      {hasAgentDraft && isCommitted ? (
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {t.agentDraftSynced}
        </p>
      ) : null}
      {qualityWarnings.length > 0 ? (
        <div className="mt-1 text-xs leading-5 text-amber-700 dark:text-amber-400">
          <p>{formatCountMessage(t.agentQualityWarnings, qualityWarnings.length)}</p>
          <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
            {qualityWarnings.map((warning) => (
              <li key={`${warning.code}:${warning.target}`}>
                {getQualityWarningLabel(warning.code, t)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="mt-3 max-h-72 space-y-1.5 overflow-y-auto pr-1 text-xs leading-5 text-muted-foreground">
        {editRows.map(({ edit, fields }) => {
          const hasDiff = fields.length > 0;

          return (
            <details
              key={edit.id}
              className="rounded-xl bg-background/45 px-2.5 py-1.5"
              open={hasDiff && edits.length === 1}
            >
              <summary className="flex cursor-pointer list-none gap-2 marker:hidden">
                <span
                  aria-hidden="true"
                  className="mt-2 size-1 rounded-full bg-current"
                />
                <span className="min-w-0 flex-1 break-words">
                  {getEditSummaryLabel(edit)}
                </span>
                {hasDiff ? (
                  <ChevronDown className="mt-1 size-3.5 shrink-0" />
                ) : null}
              </summary>
              {hasDiff ? (
                <div className="mt-2 grid gap-2">
                  {fields.map((field) => (
                    <div
                      aria-label={field.label}
                      key={field.id}
                      className="rounded-lg border border-border/60 bg-background/55 p-2"
                      role="group"
                    >
                      <dl className="grid gap-1.5">
                        <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-2">
                          <dt className="pt-1 text-[10px] font-medium uppercase tracking-[0.12em]">
                            {t.agentDiffBefore}
                          </dt>
                          <dd className="whitespace-pre-wrap rounded-md bg-muted/40 px-2 py-1">
                            {field.before}
                          </dd>
                        </div>
                        <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-2">
                          <dt className="pt-1 text-[10px] font-medium uppercase tracking-[0.12em]">
                            {t.agentDiffAfter}
                          </dt>
                          <dd className="whitespace-pre-wrap rounded-md bg-emerald-500/10 px-2 py-1 text-foreground">
                            {field.after}
                          </dd>
                        </div>
                      </dl>
                    </div>
                  ))}
                </div>
              ) : null}
            </details>
          );
        })}
      </div>
      {shouldShowDraftActions ? (
        <div className="mt-3 flex gap-2">
          <Button
            type="button"
            size="sm"
            className="h-8 flex-1 rounded-xl text-xs"
            onClick={onApplyAgentDraft}
          >
            <Check className="mr-1.5 size-3.5" />
            {t.agentApplyDraft}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 flex-1 rounded-xl text-xs"
            onClick={onDiscardAgentDraft}
          >
            <RotateCcw className="mr-1.5 size-3.5" />
            {t.agentDiscardDraft}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export default AgentChangeSummary;
