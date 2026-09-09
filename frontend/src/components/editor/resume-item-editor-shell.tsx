import { ArrowDown, ArrowUp, ChevronDown, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export function ResumeItemEditorShell({
  index,
  itemLabel,
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
  index: number;
  itemLabel: string;
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
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!initiallyOpen) {
      return;
    }

    contentRef.current
      ?.querySelector<HTMLElement>(
        'input:not([type="hidden"]):not(:disabled), textarea:not(:disabled), [contenteditable="true"]',
      )
      ?.focus();
  }, [initiallyOpen]);

  return (
    <>
      {index > 0 ? <Separator /> : null}
      <section>
        <Collapsible
          open={open}
          onOpenChange={setOpen}
          className="-mx-2 rounded-md bg-muted/35"
        >
          <div className="flex min-h-10 items-center justify-between gap-3 px-2">
            <h4 className="shrink-0 text-sm font-medium text-foreground/80">
              {itemLabel} {index + 1}
            </h4>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={!canMoveUp}
                aria-label={`${moveUpLabel} ${index + 1}`}
                onClick={onMoveUp}
              >
                <ArrowUp aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={!canMoveDown}
                aria-label={`${moveDownLabel} ${index + 1}`}
                onClick={onMoveDown}
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
              <CollapsibleTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`${toggleLabel} ${index + 1}`}
                >
                  <ChevronDown
                    aria-hidden="true"
                    className={cn(
                      "transition-transform",
                      !open && "-rotate-90",
                    )}
                  />
                </Button>
              </CollapsibleTrigger>
            </div>
          </div>
          <CollapsibleContent className="collapsible-content">
            <div
              ref={contentRef}
              className="collapsible-content-inner grid gap-3 px-2 pb-2 pt-3"
            >
              {children}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </section>
    </>
  );
}
