import { useState, type ReactNode } from "react";

import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";

export function DocumentCanvasStatusBar({ children }: { children: ReactNode }) {
  const open = Boolean(children);
  const [content, setContent] = useState(children);
  if (children && children !== content) setContent(children);

  return (
    <Collapsible open={open} className="relative z-20 shrink-0 print:hidden">
      <CollapsibleContent className="collapsible-content">
        <div
          inert={!open}
          aria-hidden={!open}
          className="collapsible-content-inner flex justify-center px-3 pt-3 pb-3 sm:px-4 sm:pt-4"
        >
          {content}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
