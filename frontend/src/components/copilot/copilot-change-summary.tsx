import type { AppMessages } from "@/i18n";
import { getAgentQualityWarnings } from "@/lib/agent-panel-state";
import type { AgentChatMessage } from "@/types/api";
import { CheckCheck, ChevronDown, TriangleAlert } from "lucide-react";

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

function formatCount(template: string, count: number) {
  return template.replace("{count}", String(count));
}

function formatReceipt(template: string, applied: number, discarded: number) {
  return template
    .replace("{applied}", String(applied))
    .replace("{discarded}", String(discarded));
}

/** Resolved drafts remain in history as a compact immutable receipt. */
export function AgentChangeSummary({
  response,
  t,
}: {
  response: AgentChatMessage | undefined;
  t: AppMessages;
}) {
  const reviewItems = response?.draft?.reviewItems ?? [];
  if (response?.transactionState === "rolled_back") {
    return null;
  }

  const qualityWarnings = getAgentQualityWarnings(response?.tools ?? []);
  const isResolved =
    reviewItems.length > 0 &&
    !reviewItems.some((item) => item.status === "pending");
  if (!isResolved && qualityWarnings.length === 0) {
    return null;
  }

  const applied = reviewItems.filter(
    (item) => item.status === "applied",
  ).length;
  const discarded = reviewItems.filter(
    (item) => item.status === "discarded",
  ).length;
  const superseded = reviewItems.filter(
    (item) => item.status === "superseded",
  ).length;
  const receipt =
    superseded === 0
      ? formatReceipt(t.agentDraftResolutionReceipt, applied, discarded)
      : applied === 0 && discarded === 0
        ? t.agentDraftSuperseded
        : [
            applied > 0 ? formatCount(t.agentDraftAppliedCount, applied) : null,
            discarded > 0
              ? formatCount(t.agentDraftDiscardedCount, discarded)
              : null,
            formatCount(t.agentDraftSupersededCount, superseded),
          ]
            .filter(Boolean)
            .join(" · ");

  return (
    <div className="mt-3 grid justify-items-start gap-1.5">
      {isResolved ? (
        <div
          className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-[11px] leading-4 text-muted-foreground"
          data-slot="agent-draft-resolution-receipt"
        >
          <CheckCheck aria-hidden="true" className="size-3.5 shrink-0" />
          <span className="min-w-0 break-words">{receipt}</span>
        </div>
      ) : null}
      {qualityWarnings.length > 0 ? (
        <details className="group max-w-full text-xs text-warning">
          <summary className="inline-flex min-h-7 cursor-pointer list-none items-center gap-1.5 rounded-full border border-warning/25 bg-warning/5 px-2.5 py-1 marker:hidden">
            <TriangleAlert aria-hidden="true" className="size-3.5 shrink-0" />
            <span className="truncate">
              {formatCount(t.agentQualityWarnings, qualityWarnings.length)}
            </span>
            <ChevronDown
              aria-hidden="true"
              className="size-3.5 shrink-0 transition-transform group-open:rotate-180"
            />
          </summary>
          <ul className="mt-1.5 grid max-w-[20rem] list-disc gap-1 rounded-xl border border-warning/20 bg-warning/5 px-3 py-2 pl-7 leading-5">
            {qualityWarnings.map((warning) => (
              <li key={`${warning.code}:${warning.target}`}>
                {getQualityWarningLabel(warning.code, t)}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export default AgentChangeSummary;
