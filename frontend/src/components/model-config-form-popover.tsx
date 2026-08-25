import { Plus } from "lucide-react";
import { isValidElement, useState, type ReactNode } from "react";

import { ModelConfigDialog } from "@/components/models/model-config-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import type { AppMessages, Locale } from "@/i18n";
import type { ModelConfig } from "@/types/resume";

export function ModelConfigFormPopover({
  t,
  locale,
  mode,
  initialConfig,
  trigger,
  onSubmit,
}: {
  t: AppMessages;
  locale: Locale;
  mode: "create" | "edit";
  initialConfig?: ModelConfig;
  trigger?: ReactNode;
  onSubmit: (value: ModelConfig) => void;
}) {
  const [open, setOpen] = useState(false);
  const triggerElement = !trigger ? (
    <Button type="button">
      <Plus data-icon="inline-start" />
      {t.addModelConfig}
    </Button>
  ) : isValidElement(trigger) ? (
    trigger
  ) : (
    <Button type="button" variant="outline">
      {trigger}
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {/* Radix must clone the concrete trigger so its behavior reaches the button. */}
        {triggerElement}
      </DialogTrigger>
      {open ? (
        <ModelConfigDialog
          initialConfig={initialConfig}
          locale={locale}
          messages={t}
          mode={mode}
          onClose={() => setOpen(false)}
          onSaved={onSubmit}
        />
      ) : null}
    </Dialog>
  );
}
