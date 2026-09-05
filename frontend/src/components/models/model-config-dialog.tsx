import { useRef, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FieldGroup } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages, Locale } from "@/i18n";
import type { ModelConfig } from "@/types/resume";

import { ModelConfigModelFields } from "./model-config-model-fields";
import { focusFirstModelConfigError } from "./model-config-focus";
import { ModelConfigProviderFields } from "./model-config-provider-fields";
import { useModelConfigDialog } from "./use-model-config-dialog";

export function ModelConfigDialog({
  initialConfig,
  locale,
  messages,
  mode,
  onClose,
  onExited,
  onSaved,
  restoreFocus,
}: {
  initialConfig?: ModelConfig;
  locale: Locale;
  messages: AppMessages;
  mode: "create" | "edit";
  onClose: () => void;
  onExited: () => void;
  onSaved: (config: ModelConfig) => void;
  restoreFocus?: () => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const initialFocusRef = useRef<HTMLHeadingElement>(null);
  const controller = useModelConfigDialog({
    initialConfig,
    locale,
    messages,
    mode,
    onSaved,
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const result = await controller.submit();

    if (result.status === "saved") {
      onClose();
    } else if (result.status === "invalid" && formRef.current) {
      focusFirstModelConfigError(
        formRef.current,
        result.errors,
        controller.draft.providerKind,
      );
    }
  }

  return (
    <DialogContent
      closeLabel={messages.close}
      className="h-[min(34rem,calc(100dvh-2rem))] overflow-hidden p-0 sm:max-w-xl [&>[data-slot=dialog-close]]:inline-flex [&>[data-slot=dialog-close]]:size-8 [&>[data-slot=dialog-close]]:items-center [&>[data-slot=dialog-close]]:justify-center"
      onOpenAutoFocus={(event) => {
        if (mode === "edit") {
          event.preventDefault();
          initialFocusRef.current?.focus({ preventScroll: true });
        }
      }}
      onCloseAutoFocus={(event) => {
        if (restoreFocus) {
          event.preventDefault();
          restoreFocus();
        }
      }}
      onAnimationEnd={(event) => {
        if (
          event.target === event.currentTarget &&
          event.currentTarget.dataset.state === "closed"
        ) {
          onExited();
        }
      }}
    >
      <form
        ref={formRef}
        noValidate
        className="flex h-full min-h-0 flex-col"
        onSubmit={(event) => void handleSubmit(event)}
      >
        <DialogHeader className="shrink-0 px-6 pt-6 pb-4">
          <DialogTitle
            ref={initialFocusRef}
            tabIndex={mode === "edit" ? -1 : undefined}
          >
            {mode === "create" ? messages.addModelConfig : messages.editModelConfig}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {mode === "create" ? messages.addModelConfig : messages.editModelConfig}
          </DialogDescription>
        </DialogHeader>

        <FieldGroup
          aria-busy={controller.modelOptionsLoading}
          className="min-h-0 flex-1 gap-5 overflow-y-auto overscroll-contain px-6 py-2"
        >
          {controller.modelOptionsLoading ? (
            <span className="sr-only" role="status">
              {controller.providersLoaded
                ? messages.fetchingModels
                : messages.modelProvidersLoading}
            </span>
          ) : null}
          <ModelConfigProviderFields
            controller={controller}
            messages={messages}
          />
          <ModelConfigModelFields
            controller={controller}
            messages={messages}
          />
        </FieldGroup>

        <DialogFooter className="shrink-0 px-6 pt-4 pb-4">
          <DialogClose asChild>
            <Button type="button" variant="outline">
              {messages.cancel}
            </Button>
          </DialogClose>
          <Button
            type="submit"
            disabled={
              controller.submitting ||
              controller.discovering ||
              controller.modelOptionsLoading ||
              !controller.selectedProvider
            }
          >
            {controller.submitting ? (
              <Spinner data-icon="inline-start" aria-label={messages.saving} />
            ) : null}
            {mode === "create"
              ? messages.createModelConfig
              : messages.saveModelConfig}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
