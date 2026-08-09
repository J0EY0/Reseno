import { Plus } from "lucide-react";
import {
  isValidElement,
  lazy,
  Suspense,
  useState,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages, Locale } from "@/i18n";
import type { ModelConfig } from "@/types/resume";

const loadModelConfigDialog = () =>
  import("@/components/models/model-config-dialog");

const LazyModelConfigDialog = lazy(() =>
  loadModelConfigDialog().then((module) => ({
    default: module.ModelConfigDialog,
  })),
);

function ModelConfigTrigger({
  children,
  messages,
}: {
  children?: ReactNode;
  messages: AppMessages;
}) {
  if (!children) {
    return (
      <Button type="button">
        <Plus data-icon="inline-start" />
        {messages.addModelConfig}
      </Button>
    );
  }

  if (isValidElement(children)) {
    return children;
  }

  return (
    <Button type="button" variant="outline">
      {children}
    </Button>
  );
}

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

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        asChild
        onFocus={() => void loadModelConfigDialog()}
        onPointerEnter={() => void loadModelConfigDialog()}
      >
        <ModelConfigTrigger messages={t}>{trigger}</ModelConfigTrigger>
      </DialogTrigger>
      {open ? (
        <Suspense
          fallback={
            <DialogContent closeLabel={t.close} className="sm:max-w-xl">
              <DialogTitle className="sr-only">
                {mode === "create" ? t.addModelConfig : t.editModelConfig}
              </DialogTitle>
              <div className="flex min-h-48 items-center justify-center">
                <Spinner aria-label={t.modelProvidersLoading} />
              </div>
            </DialogContent>
          }
        >
          <LazyModelConfigDialog
            initialConfig={initialConfig}
            locale={locale}
            messages={t}
            mode={mode}
            onClose={() => setOpen(false)}
            onSaved={onSubmit}
          />
        </Suspense>
      ) : null}
    </Dialog>
  );
}
