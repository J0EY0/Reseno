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
  const toolbarTitle =
    state.history.version?.resume.title ||
    state.resumeItem?.title ||
    messages.untitledResume;

  return (
    <header
      ref={headerRef}
      className="sticky top-0 z-20 shrink-0 border-b border-border bg-background print:hidden"
    >
      <div className="grid min-h-16 grid-cols-1 items-center gap-2 px-3 py-2 sm:h-16 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-3 sm:px-4 sm:py-0">
        <div className="flex min-w-0 items-center gap-2">
          <Button
            type="button"
            variant="outline"
            className="px-2.5 sm:px-3"
            aria-label={messages.backToResumes}
            title={messages.backToResumes}
            disabled={
              state.history.isRestoring ||
              Boolean(state.agent.review?.resolvingStatus)
            }
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
                disabled={state.editing.disabled}
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
      </div>
    </header>
  );
}
