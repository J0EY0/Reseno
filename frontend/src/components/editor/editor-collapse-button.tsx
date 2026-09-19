import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export function EditorCollapseButton({
  collapsed,
  label,
}: {
  collapsed: boolean;
  label: string;
}) {
  return (
    <CollapsibleTrigger asChild>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="cursor-pointer"
        data-slot="editor-toggle-trigger"
        aria-label={label}
      >
        <ChevronDown
          aria-hidden="true"
          className={cn("transition-transform", collapsed && "-rotate-90")}
        />
      </Button>
    </CollapsibleTrigger>
  );
}
