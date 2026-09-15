import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useEditorSortable } from "@/components/editor/use-editor-sortable";
import { EditorCollapseButton } from "@/components/editor/editor-collapse-button";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { Separator } from "@/components/ui/separator";
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
    <>
      {index > 0 ? <Separator /> : null}
      <section
        ref={setNodeRef}
        style={style}
        className="editor-sortable"
        data-resume-item-id={itemId}
        data-dragging={isDragging || undefined}
      >
        <Collapsible
          open={open}
          onOpenChange={setOpen}
          className="-mx-2 rounded-md bg-muted/35"
        >
          <div
            data-slot="editor-item-header"
            className="flex min-h-10 items-center gap-2 px-2"
          >
            <h4 className="min-w-0 flex-1">
              <TooltipProvider delayDuration={180}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      ref={setActivatorNodeRef}
                      {...attributes}
                      {...listeners}
                      type="button"
                      data-slot="editor-sort-trigger"
                      aria-label={itemTitle}
                      className="flex min-h-10 w-full items-center rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    >
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground/80">
                        {itemTitle}
                      </span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent
                    side="top"
                    hidden={isDragging}
                    className="max-w-[min(20rem,calc(100vw-2rem))] break-words data-[state=closed]:hidden"
                  >
                    {itemTitle}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </h4>
            <div className="flex shrink-0 items-center gap-1">
              <div className="editor-heading-actions flex gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={!canMoveUp}
                  aria-label={`${moveUpLabel} ${index + 1}`}
                  onClick={(event) => move(event.currentTarget, onMoveUp)}
                >
                  <ArrowUp aria-hidden="true" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={!canMoveDown}
                  aria-label={`${moveDownLabel} ${index + 1}`}
                  onClick={(event) => move(event.currentTarget, onMoveDown)}
                >
                  <ArrowDown aria-hidden="true" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
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
          <CollapsibleContent className="collapsible-content">
            <div className="collapsible-content-inner grid gap-3 px-2 pb-2 pt-3">
              {children}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </section>
    </>
  );
}
