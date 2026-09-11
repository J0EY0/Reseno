import {
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorLogo,
  ModelSelectorName,
} from "@/components/ai-elements/model-selector";
import { Button } from "@/components/ui/button";
import { Command } from "@/components/ui/command";
import type { AppMessages } from "@/i18n";
import type { ModelConfig } from "@/types/resume";
import { Check } from "lucide-react";
import { useMemo } from "react";

function getModelProvider(config: ModelConfig) {
  return {
    id: config.iconProvider || config.provider,
    label: config.providerLabel || config.provider,
  };
}

function getModelDisplayName(config: ModelConfig) {
  return config.nickname.trim() || config.model;
}

function getModelSecondaryName(config: ModelConfig) {
  const nickname = config.nickname.trim();

  if (!nickname || nickname === config.model) {
    return null;
  }

  return config.model;
}

function focusSearch(element: HTMLInputElement | null) {
  if (element?.closest('[data-slot="dialog-content"][data-state="open"]')) {
    element.focus();
  }
}

export default function CopilotModelSelectorMenu({
  modelConfigs,
  onOpenModelSettings,
  onSelect,
  selectedModelConfigId,
  t,
}: {
  modelConfigs: ModelConfig[];
  onOpenModelSettings: () => void;
  onSelect: (modelConfigId: string) => void;
  selectedModelConfigId: string;
  t: AppMessages;
}) {
  const modelGroups = useMemo(() => {
    const grouped = new Map<string, { items: ModelConfig[] }>();

    modelConfigs.forEach((config) => {
      const provider = getModelProvider(config);
      const current = grouped.get(provider.label);

      if (current) {
        current.items.push(config);
        return;
      }

      grouped.set(provider.label, { items: [config] });
    });

    return Array.from(grouped.entries());
  }, [modelConfigs]);
  return (
    <Command className="**:data-[slot=command-input-wrapper]:h-auto">
      <ModelSelectorInput
        ref={focusSearch}
        placeholder={t.agentModelSearchPlaceholder}
      />
      <ModelSelectorList>
        <ModelSelectorEmpty>
          {modelConfigs.length === 0 ? (
            <div className="grid gap-3 px-4 py-5 text-center">
              <p className="text-sm text-muted-foreground">
                {t.agentNoConfiguredModels}
              </p>
              <Button
                className="mx-auto h-8 rounded-xl px-3 text-xs"
                onClick={onOpenModelSettings}
                size="sm"
                type="button"
              >
                {t.openModelSettings}
              </Button>
            </div>
          ) : (
            t.agentNoModelsFound
          )}
        </ModelSelectorEmpty>
        {modelGroups.map(([groupName, group]) => (
          <ModelSelectorGroup heading={groupName} key={groupName}>
            {group.items.map((config) => (
              <ModelSelectorItem
                key={config.id}
                keywords={[config.nickname, config.model]}
                onSelect={() => onSelect(config.id)}
                value={config.id}
              >
                <ModelSelectorLogo provider={getModelProvider(config).id} />
                <div className="flex min-w-0 flex-1 flex-col">
                  <ModelSelectorName className="truncate font-medium">
                    {getModelDisplayName(config)}
                  </ModelSelectorName>
                  {getModelSecondaryName(config) ? (
                    <span className="truncate text-xs text-muted-foreground">
                      {getModelSecondaryName(config)}
                    </span>
                  ) : null}
                </div>
                {selectedModelConfigId === config.id ? (
                  <Check className="ml-auto size-4" />
                ) : (
                  <div className="ml-auto size-4" />
                )}
              </ModelSelectorItem>
            ))}
          </ModelSelectorGroup>
        ))}
      </ModelSelectorList>
    </Command>
  );
}
