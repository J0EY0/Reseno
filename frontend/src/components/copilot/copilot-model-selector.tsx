import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorLogo,
  ModelSelectorName,
  ModelSelectorTrigger,
} from '@/components/ai-elements/model-selector'
import { PromptInputButton } from '@/components/ai-elements/prompt-input'
import { Button } from '@/components/ui/button'
import type { AppMessages } from '@/i18n'
import { cn } from '@/lib/utils'
import type { ModelConfig } from '@/types/resume'
import { Check } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { toast } from 'sonner'

function getModelProvider(config: ModelConfig) {
  return {
    id: config.iconProvider || config.provider,
    label: config.providerLabel || config.provider,
  }
}

function getModelDisplayName(config: ModelConfig) {
  return config.nickname.trim() || config.model
}

function getModelTriggerName(config: ModelConfig) {
  const raw = config.model.trim()

  if (!raw) {
    return ''
  }

  if (raw.toLowerCase().startsWith('claude-')) {
    return raw.replace(/^claude-/i, '').toUpperCase()
  }

  return raw.toUpperCase()
}

function getModelSecondaryName(config: ModelConfig) {
  const nickname = config.nickname.trim()

  if (!nickname || nickname === config.model) {
    return null
  }

  return config.model
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
  appliesToNextMessage: boolean
  disabled: boolean
  modelConfigs: ModelConfig[]
  onOpenModelSettings: () => void
  onSelectedModelConfigChange: (modelConfigId: string) => void
  selectedModelConfig: ModelConfig | null
  selectedModelConfigId: string
  t: AppMessages
}) {
  const [open, setOpen] = useState(false)
  const modelGroups = useMemo(() => {
    const grouped = new Map<string, { items: ModelConfig[] }>()

    modelConfigs.forEach((config) => {
      const provider = getModelProvider(config)
      const current = grouped.get(provider.label)

      if (current) {
        current.items.push(config)
        return
      }

      grouped.set(provider.label, { items: [config] })
    })

    return Array.from(grouped.entries())
  }, [modelConfigs])
  const handleModelSelect = useCallback(
    (modelConfigId: string) => {
      const changed = modelConfigId !== selectedModelConfigId
      onSelectedModelConfigChange(modelConfigId)
      setOpen(false)

      // The selector controls the next accepted user turn. The active run owns
      // an immutable backend snapshot and continues with its original model.
      if (changed && appliesToNextMessage) {
        toast.info(t.agentModelChangedNextTurn, { closeButton: true })
      }
    },
    [
      appliesToNextMessage,
      onSelectedModelConfigChange,
      selectedModelConfigId,
      t.agentModelChangedNextTurn,
    ],
  )

  const selectedModelConfigDisplayName = selectedModelConfig
    ? getModelDisplayName(selectedModelConfig)
    : ''
  const selectedModelConfigTriggerName = selectedModelConfig
    ? getModelTriggerName(selectedModelConfig)
    : ''
  const triggerAriaLabel = selectedModelConfig
    ? appliesToNextMessage
      ? t.agentModelNextTurnAria.replace(
          '{model}',
          selectedModelConfigDisplayName,
        )
      : selectedModelConfigDisplayName
    : t.agentModelConfigureHover

  return (
    <ModelSelector open={open} onOpenChange={setOpen}>
      <ModelSelectorTrigger asChild>
        <PromptInputButton
          aria-label={triggerAriaLabel}
          className="h-8 w-fit min-w-0 max-w-none justify-start text-foreground transition-colors duration-200"
          disabled={disabled}
          size="sm"
          title={selectedModelConfig ? undefined : t.agentModelConfigureHover}
        >
          {selectedModelConfig ? (
            <ModelSelectorLogo
              provider={getModelProvider(selectedModelConfig).id}
            />
          ) : (
            <span aria-hidden="true" className="size-4 shrink-0" />
          )}
          <ModelSelectorName
            className={cn(
              'flex-none overflow-visible text-clip whitespace-nowrap text-[12px] font-medium',
              !selectedModelConfig && 'text-muted-foreground',
            )}
          >
            {selectedModelConfig
              ? selectedModelConfigTriggerName
              : t.agentModelNotConfigured}
          </ModelSelectorName>
        </PromptInputButton>
      </ModelSelectorTrigger>
      <ModelSelectorContent>
        <ModelSelectorInput placeholder={t.agentModelSearchPlaceholder} />
        <ModelSelectorList>
          <ModelSelectorEmpty>
            {modelConfigs.length === 0 ? (
              <div className="grid gap-3 px-4 py-5 text-center">
                <p className="text-sm text-muted-foreground">
                  {t.agentNoConfiguredModels}
                </p>
                <Button
                  className="mx-auto h-8 rounded-xl px-3 text-xs"
                  onClick={() => {
                    setOpen(false)
                    onOpenModelSettings()
                  }}
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
                  onSelect={() => handleModelSelect(config.id)}
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
      </ModelSelectorContent>
    </ModelSelector>
  )
}
