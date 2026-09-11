import { Plus } from "lucide-react";
import { lazy, Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import type { AppMessages } from "@/i18n";
import type { SectionKind } from "@/types/resume";

const loadAddSectionMenu = () => import("./add-section-menu");
const AddSectionMenu = lazy(loadAddSectionMenu);

function preloadAddSectionMenu() {
  void loadAddSectionMenu().catch(() => undefined);
}

export function AddSectionPopover({
  t,
  onSelect,
}: {
  t: AppMessages;
  onSelect: (kind: SectionKind) => void;
}) {
  const [open, setOpen] = useState(false);

  function selectKind(kind: SectionKind) {
    setOpen(false);
    onSelect(kind);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="h-10 rounded-xl border-dashed bg-background/95"
          onPointerEnter={preloadAddSectionMenu}
          onFocus={preloadAddSectionMenu}
        >
          <Plus aria-hidden="true" data-icon="inline-start" />
          {t.addSection}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        aria-label={t.addSectionPickerTitle}
        align="center"
        className="w-[360px] max-w-[calc(100vw-2rem)] p-0"
      >
        {open ? (
          <Suspense
            fallback={
              <div aria-busy="true" className="grid gap-2 p-2">
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
              </div>
            }
          >
            <AddSectionMenu t={t} onSelect={selectKind} />
          </Suspense>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
