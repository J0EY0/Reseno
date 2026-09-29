import { History } from "lucide-react";
import { useId } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { Locale } from "@/i18n";
import historyMessages from "@/i18n/resume-history.json";
import type { ResumeDetailResponse } from "@/types/api";

export function ResumeHistoryToolbar({
  locale,
  historyVersion,
  isRestoring,
  hasRestoreError,
  onRestore,
  onReturn,
}: {
  locale: Locale;
  historyVersion: ResumeDetailResponse;
  isRestoring: boolean;
  hasRestoreError: boolean;
  onRestore: () => void;
  onReturn: () => void;
}) {
  const messages = historyMessages[locale];
  const descriptionId = useId();
  const savedAt = new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(historyVersion.savedAt));

  return (
    <section
      aria-label={messages.viewing}
      data-slot="resume-history-toolbar"
      className="flex max-w-full flex-wrap items-center justify-center gap-x-3 gap-y-2 rounded-lg border bg-background/95 p-2 shadow-md"
    >
      <div role="status" className="flex min-w-0 items-center gap-2 px-1">
        <History
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground"
        />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium">{messages.viewing}</span>
            <Badge variant="secondary">{messages.readOnly}</Badge>
          </div>
          <time
            dateTime={historyVersion.savedAt}
            className="block text-xs tabular-nums text-muted-foreground"
          >
            {savedAt}
          </time>
        </div>
      </div>
      <p id={descriptionId} className="sr-only">
        {messages.description}
      </p>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={isRestoring}
          onClick={(event) => {
            event.currentTarget
              .closest(".resume-preview-card")
              ?.querySelector<HTMLElement>(
                '[data-slot="document-canvas-viewport"]',
              )
              ?.focus({ preventScroll: true });
            onReturn();
          }}
        >
          {messages.returnToLatest}
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={isRestoring}
          aria-busy={isRestoring}
          aria-describedby={descriptionId}
          title={messages.description}
          onClick={onRestore}
        >
          {isRestoring ? (
            <Spinner data-icon="inline-start" aria-hidden="true" />
          ) : null}
          {isRestoring ? messages.restoring : messages.restore}
        </Button>
      </div>
      {hasRestoreError ? (
        <p
          role="alert"
          className="w-full px-1 text-center text-xs text-destructive"
        >
          {messages.restoreFailed}
        </p>
      ) : null}
    </section>
  );
}
