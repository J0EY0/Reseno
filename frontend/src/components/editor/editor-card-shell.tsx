import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { ResourceErrorBoundary } from "@/components/resource-error-boundary";
import type { EditorSortActivator } from "@/components/editor/use-editor-sortable";
import { EditorCollapseButton } from "@/components/editor/editor-collapse-button";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";

export function EditorCardShell({
  icon: Icon,
  title,
  titleMeta,
  toggleLabel,
  collapsed,
  onToggle,
  headerAction,
  sort,
  children,
}: {
  icon: LucideIcon;
  title: string;
  titleMeta?: string;
  toggleLabel: string;
  collapsed: boolean;
  onToggle: () => void;
  headerAction?: ReactNode;
  sort?: EditorSortActivator;
  children: ReactNode;
}) {
  const Title = sort ? "button" : "div";

  return (
    <section
      data-collapsed={collapsed ? "true" : "false"}
      className="min-w-0 border-b border-border/70"
    >
      <Collapsible open={!collapsed} onOpenChange={onToggle}>
        <div
          data-slot="editor-card-header"
          className="flex min-h-[60px] items-center gap-2 py-2"
        >
          <h3 className="min-w-0 flex-1">
            <Title
              ref={sort?.setActivatorNodeRef}
              {...sort?.attributes}
              {...sort?.listeners}
              type={sort ? "button" : undefined}
              data-slot={sort ? "editor-sort-trigger" : "editor-title"}
              aria-label={sort ? title : undefined}
              className="flex min-h-9 w-full items-center gap-2.5 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            >
              <Icon
                aria-hidden="true"
                className="size-[18px] shrink-0 text-muted-foreground"
              />
              <span className="flex min-w-0 items-baseline gap-2 text-sm font-medium leading-5">
                <span className="min-w-0 truncate" title={title}>
                  {title}
                </span>
                {titleMeta ? (
                  <span className="hidden shrink-0 whitespace-nowrap text-xs font-normal leading-4 text-muted-foreground sm:inline">
                    {titleMeta}
                  </span>
                ) : null}
              </span>
            </Title>
          </h3>
          <div className="flex shrink-0 items-center">
            {headerAction ? (
              <div className="editor-heading-actions">
                <ResourceErrorBoundary className="fixed bottom-4 right-4 z-50 max-w-sm bg-background shadow-lg">
                  {headerAction}
                </ResourceErrorBoundary>
              </div>
            ) : null}
            <EditorCollapseButton collapsed={collapsed} label={toggleLabel} />
          </div>
        </div>
        <CollapsibleContent className="collapsible-content">
          <div className="collapsible-content-inner grid gap-6 pb-3">
            <ResourceErrorBoundary>{children}</ResourceErrorBoundary>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
