import { PromptInputButton } from "@/components/ai-elements/prompt-input";
import { ModelProviderIcon } from "@/components/model-provider-icon";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type { ModelConfig } from "@/types/resume";
import { lazy, Suspense, useCallback, useState } from "react";
import { toast } from "sonner";

const loadModelSelectorMenu = () => import("./copilot-model-selector-menu");
const CopilotModelSelectorMenu = lazy(loadModelSelectorMenu);

function preloadModelSelectorMenu() {
  void loadModelSelectorMenu().catch(() => undefined);
}

function getModelTriggerName(config: ModelConfig) {
  const raw = config.model.trim();

  if (!raw) {
    return "";
  }

  if (raw.toLowerCase().startsWith("claude-")) {
    return raw.replace(/^claude-/i, "").toUpperCase();
  }

  return raw.toUpperCase();
}

export function CopilotModelSelector({
  appliesToNextMessage,
  disabled,
  modelConfigs,
  onOpenModelSettings,
  onSelectedModelConfigChange,
  selectedModelConfig,
  selectedModelConfigId,
  t,
}: {
  appliesToNextMessage: boolean;
  disabled: boolean;
  modelConfigs: ModelConfig[];
  onOpenModelSettings: () => void;
  onSelectedModelConfigChange: (modelConfigId: string) => void;
  selectedModelConfig: ModelConfig | null;
  selectedModelConfigId: string;
  t: AppMessages;
}) {
  const [open, setOpen] = useState(false);
  const handleModelSelect = useCallback(
    (modelConfigId: string) => {
      const changed = modelConfigId !== selectedModelConfigId;
      onSelectedModelConfigChange(modelConfigId);
      setOpen(false);

      // The selector controls the next accepted user turn. The active run owns
      // an immutable backend snapshot and continues with its original model.
      if (changed && appliesToNextMessage) {
        toast.info(t.agentModelChangedNextTurn, { closeButton: true });
      }
    },
    [
      appliesToNextMessage,
      onSelectedModelConfigChange,
      selectedModelConfigId,
      t.agentModelChangedNextTurn,
    ],
  );

  const selectedModelConfigDisplayName = selectedModelConfig
    ? selectedModelConfig.nickname.trim() || selectedModelConfig.model
    : "";
  const selectedModelConfigTriggerName = selectedModelConfig
    ? getModelTriggerName(selectedModelConfig)
    : "";
  const triggerAriaLabel = selectedModelConfig
    ? appliesToNextMessage
      ? t.agentModelNextTurnAria.replace(
          "{model}",
          selectedModelConfigDisplayName,
        )
      : selectedModelConfigDisplayName
    : t.agentModelConfigureHover;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <PromptInputButton
          aria-label={triggerAriaLabel}
          className="h-8 w-fit min-w-0 max-w-full shrink justify-start text-foreground transition-colors duration-200"
          disabled={disabled}
          onPointerEnter={preloadModelSelectorMenu}
          onFocus={preloadModelSelectorMenu}
          size="sm"
          title={selectedModelConfig?.model || t.agentModelConfigureHover}
        >
          {selectedModelConfig ? (
            <ModelProviderIcon
              className="inline-flex size-4 shrink-0 items-center justify-center text-foreground"
              provider={
                selectedModelConfig.iconProvider || selectedModelConfig.provider
              }
              size={16}
              type="color"
            />
          ) : (
            <span aria-hidden="true" className="size-4 shrink-0" />
          )}
          <span
            className={cn(
              "flex-1 truncate text-left min-w-0 text-[12px] font-medium",
              !selectedModelConfig && "text-muted-foreground",
            )}
          >
            {selectedModelConfig
              ? selectedModelConfigTriggerName
              : t.agentModelNotConfigured}
          </span>
        </PromptInputButton>
      </DialogTrigger>
      <DialogContent
        aria-describedby={undefined}
        className="outline! border-none! p-0 outline-border! outline-solid!"
        closeLabel={t.close}
      >
        <DialogTitle className="sr-only">{t.agentSelectModel}</DialogTitle>
        <Suspense
          fallback={
            <div aria-busy="true" className="grid gap-2 p-2">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          }
        >
          <CopilotModelSelectorMenu
            modelConfigs={modelConfigs}
            selectedModelConfigId={selectedModelConfigId}
            t={t}
            onSelect={handleModelSelect}
            onOpenModelSettings={() => {
              setOpen(false);
              onOpenModelSettings();
            }}
          />
        </Suspense>
      </DialogContent>
    </Dialog>
  );
}
