import type { ReactNode } from "react";

import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";

export default function TemplateFieldsPanel({
  id,
  open,
  children,
}: {
  id?: string;
  open: boolean;
  children: ReactNode;
}) {
  return (
    <Collapsible open={open}>
      <CollapsibleContent id={id} inert={!open} className="collapsible-content">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}
