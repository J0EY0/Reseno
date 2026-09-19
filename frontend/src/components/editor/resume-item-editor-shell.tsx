import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useEditorSortable } from "@/components/editor/use-editor-sortable";
import { EditorCollapseButton } from "@/components/editor/editor-collapse-button";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getRichTextPlainText } from "@/lib/rich-text";

export function ResumeItemEditorShell({
  itemId,
  index,
  itemLabel,
  title,
  titleEditor,
  summary,
  initiallyOpen = false,
  canMoveUp,
  canMoveDown,
  removeLabel,
  moveUpLabel,
  moveDownLabel,
  toggleLabel,
  onRemove,
  onMoveUp,
  onMoveDown,
  children,
}: {
  itemId: string;
  index: number;
  itemLabel: string;
  title: string;
  titleEditor: ReactNode;
  summary?: string;
  initiallyOpen?: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  removeLabel: string;
  moveUpLabel: string;
  moveDownLabel: string;
  toggleLabel: string;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const itemTitle =
    getRichTextPlainText(title).trim() || `${itemLabel} ${index + 1}`;
  const {
    setNodeRef,
    style,
    isDragging,
    move,
    activator: { setActivatorNodeRef, attributes, listeners },
  } = useEditorSortable(itemId, itemTitle);

  return (
    <section
      ref={setNodeRef}
      style={style}
      className="editor-sortable"
      data-resume-item-id={itemId}
      data-dragging={isDragging || undefined}
      data-open={open}
    >
      <Collapsible open={open} onOpenChange={setOpen}>
        <div data-slot="editor-item-header">
          <TooltipProvider delayDuration={180}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div
                  ref={setActivatorNodeRef}
                  {...attributes}
                  {...listeners}
                  role="group"
                  aria-pressed={undefined}
                  data-slot="editor-sort-trigger"
                  aria-label={itemTitle}
                  className="flex min-h-12 items-start gap-2 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                >
                  <div className="min-w-0 flex-1">
                    <div className="min-h-9">
                      {open ? (
                        <>
                          <h4 className="sr-only">{itemTitle}</h4>
                          {titleEditor}
                        </>
                      ) : (
                        <h4 className="flex h-9 min-w-0 items-center rounded-md border border-transparent px-3 text-base font-medium md:text-sm">
                          <span className="truncate">{itemTitle}</span>
                        </h4>
                      )}
                    </div>
                    {summary ? (
                      <div className="editor-item-summary" aria-hidden={open}>
                        <div className="min-h-0 overflow-hidden">
                          <p className="truncate px-3 text-xs text-muted-foreground">
                            {summary}
                          </p>
                        </div>
                      </div>
                    ) : null}
                  </div>
                  <div className="flex min-h-9 shrink-0 items-center">
                    <div className="editor-heading-actions flex">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        disabled={!canMoveUp}
                        aria-label={`${moveUpLabel} ${index + 1}`}
                        onClick={(event) => move(event.currentTarget, onMoveUp)}
                      >
                        <ArrowUp aria-hidden="true" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        disabled={!canMoveDown}
                        aria-label={`${moveDownLabel} ${index + 1}`}
                        onClick={(event) =>
                          move(event.currentTarget, onMoveDown)
                        }
                      >
                        <ArrowDown aria-hidden="true" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`${removeLabel} ${index + 1}`}
                        onClick={onRemove}
                      >
                        <Trash2 aria-hidden="true" />
                      </Button>
                    </div>
                    <EditorCollapseButton
                      collapsed={!open}
                      label={`${toggleLabel} ${index + 1}`}
                    />
                  </div>
                </div>
              </TooltipTrigger>
              {!open && !isDragging ? (
                <TooltipContent
                  side="top"
                  className="max-w-[min(20rem,calc(100vw-2rem))] break-words data-[state=closed]:hidden"
                >
                  {itemTitle}
                </TooltipContent>
              ) : null}
            </Tooltip>
          </TooltipProvider>
        </div>
        <CollapsibleContent className="collapsible-content">
          <div className="collapsible-content-inner grid gap-6 pb-3 pt-3">
            {children}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
