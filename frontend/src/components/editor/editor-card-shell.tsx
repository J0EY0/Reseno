import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { ResourceErrorBoundary } from "@/components/resource-error-boundary";
import type { EditorSortActivator } from "@/components/editor/use-editor-sortable";
import { EditorCollapseButton } from "@/components/editor/editor-collapse-button";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

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
    <Card
      data-collapsed={collapsed ? "true" : "false"}
      className={cn(
        "gap-0 overflow-hidden border-border/75 py-0 transition-[border-color,box-shadow] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]",
        !collapsed && "border-primary/20",
      )}
    >
      <Collapsible open={!collapsed} onOpenChange={onToggle}>
        <div
          data-slot="editor-card-header"
          className="flex min-h-[60px] items-center gap-2 px-4 py-3"
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
              <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/8 text-primary">
                <Icon aria-hidden="true" className="size-4" />
              </span>
              <span className="flex min-w-0 items-baseline gap-2 text-sm font-semibold leading-5 tracking-tight">
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
          <div className="flex shrink-0 items-center gap-1">
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
          <CardContent className="collapsible-content-inner grid gap-4 border-t border-border/70 p-4">
            <ResourceErrorBoundary>{children}</ResourceErrorBoundary>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
