import { CopyPlus } from "lucide-react";
import {
  isValidElement,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ModelConfigDialog } from "@/components/models/model-config-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import type { AppMessages, Locale } from "@/i18n";
import type { ModelConfig } from "@/types/resume";

export function ModelConfigFormPopover({
  t,
  locale,
  mode,
  defaultOpen = false,
  initialConfig,
  trigger,
  restoreFocus,
  onSubmit,
}: {
  t: AppMessages;
  locale: Locale;
  mode: "create" | "edit";
  defaultOpen?: boolean;
  initialConfig?: ModelConfig;
  trigger?: ReactNode | null;
  restoreFocus?: () => void;
  onSubmit: (value: ModelConfig) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const nextDialogSessionRef = useRef(defaultOpen ? 1 : 0);
  const [dialogSession, setDialogSession] = useState<number | null>(
    defaultOpen ? 1 : null,
  );

  useEffect(() => {
    if (open || dialogSession === null) {
      return;
    }

    const fallbackTimer = window.setTimeout(() => {
      setDialogSession(null);
    }, 250);
    return () => window.clearTimeout(fallbackTimer);
  }, [dialogSession, open]);

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen && !open) {
      nextDialogSessionRef.current += 1;
      setDialogSession(nextDialogSessionRef.current);
    }
    setOpen(nextOpen);
  }

  const triggerElement = trigger === undefined ? (
    <Button type="button">
      <CopyPlus data-icon="inline-start" />
      {t.addModelConfig}
    </Button>
  ) : trigger === null ? null : isValidElement(trigger) ? (
    trigger
  ) : (
    <Button type="button" variant="outline">
      {trigger}
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      {triggerElement ? (
        <DialogTrigger asChild>
          {/* Radix must clone the concrete trigger so its behavior reaches the button. */}
          {triggerElement}
        </DialogTrigger>
      ) : null}
      {dialogSession !== null ? (
        <ModelConfigDialog
          key={dialogSession}
          initialConfig={initialConfig}
          locale={locale}
          messages={t}
          mode={mode}
          onClose={() => handleOpenChange(false)}
          onExited={() => setDialogSession(null)}
          onSaved={onSubmit}
          restoreFocus={restoreFocus}
        />
      ) : null}
    </Dialog>
  );
}
