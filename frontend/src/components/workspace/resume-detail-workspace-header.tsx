import { ChevronLeft, Pencil } from "lucide-react";
import { lazy, Suspense, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { AppMessages, Locale } from "@/i18n";

const ResumeDetailHeaderActions = lazy(() =>
  import("@/components/workspace/resume-detail-header-actions").then(
    ({ ResumeDetailHeaderActions: Component }) => ({ default: Component }),
  ),
);
const COMPACT_HEADER_MEDIA_QUERY = "(max-width: 1279px)";

export function ResumeDetailWorkspaceHeader({
  headerRef,
  locale,
  messages,
  model,
  onLocaleChange,
}: {
  headerRef: RefObject<HTMLElement | null>;
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  onLocaleChange: (locale: Locale) => void;
}) {
  const { commands, state } = model;
  const isCompactHeader = useMediaQuery(COMPACT_HEADER_MEDIA_QUERY);
  const toolbarTitle = state.resumeItem?.title || messages.untitledResume;

  return (
    <header
      ref={headerRef}
      className="sticky top-0 z-20 grid h-16 shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b border-border bg-background px-3 print:hidden sm:gap-3 sm:px-4"
    >
      <div className="flex min-w-0 items-center gap-2">
        <Button
          type="button"
          variant="outline"
          className="px-2.5 sm:px-3"
          aria-label={messages.backToResumes}
          title={messages.backToResumes}
          onClick={commands.back}
        >
          <ChevronLeft className="size-4" />
          <span className="hidden sm:inline">{messages.backToResumes}</span>
        </Button>
        {!state.hasLoadError ? (
          <div className="flex min-w-0 items-center gap-1">
            <h1
              className="truncate text-sm font-medium text-foreground xl:max-w-[min(26vw,32rem)]"
              title={toolbarTitle}
            >
              {toolbarTitle}
            </h1>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={messages.editResumeTitle}
              onClick={() => commands.setTitleDialogOpen(true)}
            >
              <Pencil className="size-3.5 text-muted-foreground" />
            </Button>
          </div>
        ) : (
          <h1 className="text-sm font-medium text-foreground">
            {messages.myResume}
          </h1>
        )}
      </div>

      <div className="flex min-w-0 items-center justify-end gap-2">
        <Suspense
          fallback={
            <div
              aria-hidden="true"
              className={
                isCompactHeader ? "h-9 w-[124px]" : "h-9 w-[min(52vw,46rem)]"
              }
            />
          }
        >
          <ResumeDetailHeaderActions
            compact={isCompactHeader}
            locale={locale}
            messages={messages}
            model={model}
            onLocaleChange={onLocaleChange}
          />
        </Suspense>
      </div>
    </header>
  );
}
