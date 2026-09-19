import { Ellipsis, Pencil, Trash2 } from "lucide-react";
import { lazy, Suspense, useRef, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import type { ResumeSectionMutation } from "@/lib/resume-section-mutations";
import type { ResumeSection } from "@/types/resume";

const ResumeSectionNameField = lazy(() =>
  import("./resume-section-content").then((module) => ({
    default: module.ResumeSectionNameField,
  })),
);

const ResumeSectionDeleteDialog = lazy(() =>
  import("./resume-section-delete-dialog").then((module) => ({
    default: module.ResumeSectionDeleteDialog,
  })),
);

export type ResumeSectionAction = "rename" | "delete" | null;

export function ResumeSectionActions({
  t,
  section,
  sectionTitle,
  onMutation,
  onRemoveSection,
  menuOpen,
  onMenuOpenChange,
  action,
  onActionChange,
  pendingActionRef,
  focusFirstItemRef,
}: {
  t: AppMessages;
  section: ResumeSection;
  sectionTitle: string;
  onMutation: (mutation: ResumeSectionMutation) => void;
  onRemoveSection: (sectionId: string) => void;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  action: ResumeSectionAction;
  onActionChange: (action: ResumeSectionAction) => void;
  pendingActionRef: RefObject<ResumeSectionAction>;
  focusFirstItemRef: RefObject<boolean>;
}) {
  const renameDismissedOutside = useRef(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const firstItemRef = useRef<HTMLDivElement>(null);

  function restoreFocus(event: Event) {
    event.preventDefault();
    triggerRef.current?.focus();
  }

  return (
    <>
      <Popover
        open={action === "rename"}
        onOpenChange={(open) => onActionChange(open ? "rename" : null)}
      >
        <DropdownMenu open={menuOpen} onOpenChange={onMenuOpenChange}>
          <PopoverAnchor asChild>
            <DropdownMenuTrigger asChild>
              <Button
                ref={triggerRef}
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={`${sectionTitle}: ${t.moreActions}`}
                title={t.moreActions}
              >
                <Ellipsis aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
          </PopoverAnchor>
          <DropdownMenuContent
            align="end"
            onFocus={(event) => {
              if (
                event.target !== event.currentTarget ||
                !focusFirstItemRef.current
              )
                return;
              focusFirstItemRef.current = false;
              firstItemRef.current?.focus();
            }}
            onCloseAutoFocus={(event) => {
              if (pendingActionRef.current === null) return;
              event.preventDefault();
              onActionChange(pendingActionRef.current);
              pendingActionRef.current = null;
            }}
          >
            <DropdownMenuGroup>
              <DropdownMenuItem
                ref={firstItemRef}
                onSelect={() => {
                  pendingActionRef.current = "rename";
                }}
              >
                <Pencil aria-hidden="true" />
                {t.renameSectionAction}
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => {
                  pendingActionRef.current = "delete";
                }}
              >
                <Trash2 aria-hidden="true" />
                {t.deleteSection}
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <PopoverContent
          align="end"
          aria-label={`${sectionTitle}: ${t.renameSectionAction}`}
          onInteractOutside={() => {
            renameDismissedOutside.current = true;
          }}
          onCloseAutoFocus={(event) => {
            if (renameDismissedOutside.current) {
              event.preventDefault();
              renameDismissedOutside.current = false;
              return;
            }
            restoreFocus(event);
          }}
        >
          <Suspense
            fallback={
              <div
                aria-busy="true"
                className="flex h-16 items-center justify-center"
              >
                <Spinner />
              </div>
            }
          >
            <ResumeSectionNameField
              t={t}
              section={section}
              onMutation={onMutation}
            />
          </Suspense>
        </PopoverContent>
      </Popover>
      <Suspense fallback={null}>
        <ResumeSectionDeleteDialog
          open={action === "delete"}
          sectionId={section.id}
          t={t}
          onOpenChange={(open) => onActionChange(open ? "delete" : null)}
          onCloseAutoFocus={restoreFocus}
          onRemoveSection={onRemoveSection}
        />
      </Suspense>
    </>
  );
}
