import { Button } from "@/components/ui/button";
import type { AppMessages } from "@/i18n";
import { getAgentQualityWarningCount } from "@/lib/agent-panel-state";
import { isAgentEditExecutionTool } from "@/lib/agent-tool-display";
import type {
  AgentChatMessage,
  AgentResumeEditSuggestion,
  AgentToolInvocation,
} from "@/types/api";
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function toReadableDiffValue(value: unknown) {
  if (typeof value === "string") {
    return value.trim();
  }

  if (!isRecord(value)) {
    return "";
  }

  const fields = [
    value.title,
    value.subtitle,
    value.organization,
    value.role,
    value.description,
    value.summary,
  ]
    .filter((field): field is string => typeof field === "string")
    .map((field) => field.trim())
    .filter(Boolean);

  if (Array.isArray(value.highlights)) {
    fields.push(
      ...value.highlights
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean),
    );
  }

  if (fields.length) {
    return fields.join("\n");
  }

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

function getEditObservationMap(tools: AgentToolInvocation[]) {
  const map = new Map<string, { before?: string; after?: string }>();

  tools.forEach((tool) => {
    if (!isAgentEditExecutionTool(tool) || !isRecord(tool.output)) {
      return;
    }

    const observations = tool.output.observations;
    if (!Array.isArray(observations)) {
      return;
    }

    observations.forEach((observation) => {
      if (!isRecord(observation) || typeof observation.target !== "string") {
        return;
      }

      map.set(observation.target, {
        before: toReadableDiffValue(observation.before),
        after: toReadableDiffValue(observation.after),
      });
    });
  });

  return map;
}

/**
 * Owns the edit observation decoding and all draft-review presentation so the
 * message row only decides where the summary belongs.
 */
export function AgentChangeSummary({
  hasAgentDraft,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  response,
  shouldShowDraftActions,
  t,
}: {
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
  const observations = getEditObservationMap(tools);
  const qualityWarningCount = getAgentQualityWarningCount(tools);
  const isCommitted = response?.transactionState === "committed";

  return (
    <div className="mt-4 rounded-2xl border border-border/70 bg-muted/25 p-3">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        <ClipboardList className="size-3.5" />
        {t.agentChangeSummaryTitle}
      </div>
      {isCommitted ? (
        <p className="mt-2 text-sm font-medium text-foreground">
          {formatCountMessage(t.agentReviewReady, edits.length)}
        </p>
      ) : null}
      {hasAgentDraft && isCommitted ? (
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {t.agentDraftSynced}
        </p>
      ) : null}
      {qualityWarningCount > 0 ? (
        <p className="mt-1 text-xs leading-5 text-amber-700 dark:text-amber-400">
          {formatCountMessage(t.agentQualityWarnings, qualityWarningCount)}
        </p>
      ) : null}
      <div className="mt-3 max-h-72 space-y-1.5 overflow-y-auto pr-1 text-xs leading-5 text-muted-foreground">
        {edits.map((edit) => {
          const observation = observations.get(edit.target);
          const hasDiff = Boolean(observation?.before || observation?.after);

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
                  {observation?.before ? (
                    <div>
                      <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.14em]">
                        {t.agentDiffBefore}
                      </div>
                      <p className="whitespace-pre-wrap rounded-lg bg-muted/40 p-2">
                        {observation.before}
                      </p>
                    </div>
                  ) : null}
                  {observation?.after ? (
                    <div>
                      <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.14em]">
                        {t.agentDiffAfter}
                      </div>
                      <p className="whitespace-pre-wrap rounded-lg bg-emerald-500/10 p-2 text-foreground">
                        {observation.after}
                      </p>
                    </div>
                  ) : null}
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
