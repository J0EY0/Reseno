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
  onSaved,
}: {
  initialConfig?: ModelConfig;
  locale: Locale;
  messages: AppMessages;
  mode: "create" | "edit";
  onClose: () => void;
  onSaved: (config: ModelConfig) => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
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
      className="overflow-hidden p-0 sm:max-w-xl"
    >
      <form
        ref={formRef}
        noValidate
        className="flex max-h-[min(680px,calc(100dvh-2rem))] min-h-0 flex-col"
        onSubmit={(event) => void handleSubmit(event)}
      >
        <DialogHeader className="shrink-0 px-6 pt-6">
          <DialogTitle>
            {mode === "create" ? messages.addModelConfig : messages.editModelConfig}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {mode === "create" ? messages.addModelConfig : messages.editModelConfig}
          </DialogDescription>
        </DialogHeader>

        <FieldGroup
          aria-busy={controller.modelOptionsLoading}
          className="min-h-0 flex-1 gap-5 overflow-y-auto overscroll-contain px-6 py-6"
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

        <DialogFooter className="shrink-0 px-6 pb-6">
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
