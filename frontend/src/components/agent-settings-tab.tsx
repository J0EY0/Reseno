import { Bot, Gauge, Languages, ShieldCheck } from "lucide-react";

import { ModelProviderIcon } from "@/components/model-provider-icon";
import {
  OptionSelect,
  SettingsRow,
  SettingsSection,
} from "@/components/settings-controls";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { TabsContent } from "@/components/ui/tabs";
import type { AppMessages } from "@/i18n";
import type {
  AgentBehaviorMode,
  AgentConfirmationMode,
  AgentResponseLanguage,
  AgentSettings,
  ModelConfig,
} from "@/types/resume";

function ModelOption({
  config,
  notConfiguredLabel,
}: {
  config: ModelConfig;
  notConfiguredLabel: string;
}) {
  const label =
    config.nickname.trim() || config.model.trim() || notConfiguredLabel;

  return (
    <div className="flex min-w-0 items-center gap-2">
      <ModelProviderIcon
        provider={config.iconProvider || config.provider}
        size={18}
      />
      <span className="truncate">{label}</span>
    </div>
  );
}

export function AgentSettingsTab({
  t,
  agentSettings,
  onAgentSettingsChange,
  modelConfigs,
}: {
  t: AppMessages;
  agentSettings: AgentSettings;
  onAgentSettingsChange: (value: AgentSettings) => void;
  modelConfigs: ModelConfig[];
}) {
  const behaviorItems: Array<{ value: AgentBehaviorMode; label: string }> = [
    { value: "balanced", label: t.agentBehaviorBalanced },
    { value: "strict", label: t.agentBehaviorStrict },
    { value: "aggressive", label: t.agentBehaviorAggressive },
  ];
  const confirmationItems: Array<{
    value: AgentConfirmationMode;
    label: string;
  }> = [
    { value: "always", label: t.agentConfirmationAlways },
    { value: "suggestOnly", label: t.agentConfirmationSuggestOnly },
  ];
  const responseLanguageItems: Array<{
    value: AgentResponseLanguage;
    label: string;
  }> = [
    { value: "follow", label: t.followResumeLanguage },
    { value: "zh", label: t.languageChinese },
    { value: "en", label: t.languageEnglish },
  ];
  const agentModelConfigs = modelConfigs.filter(
    (config) => config.supportsTools,
  );
  const selectedDefaultModelConfig =
    agentModelConfigs.find(
      (config) => config.id === agentSettings.defaultModelConfigId,
    ) ?? null;

  return (
    <TabsContent value="agent" className="mt-5 flex flex-col gap-6">
      <SettingsSection title={t.agentModelSettingsTitle}>
        <SettingsRow
          icon={<Bot />}
          label={t.defaultAgentModel}
          description={t.defaultAgentModelHint}
        >
          <Select
            value={selectedDefaultModelConfig?.id}
            disabled={agentModelConfigs.length === 0}
            onValueChange={(value) =>
              onAgentSettingsChange({
                ...agentSettings,
                defaultModelConfigId: value,
              })
            }
          >
            <SelectTrigger
              aria-label={t.defaultAgentModel}
              className="ml-auto w-full sm:max-w-64"
            >
              <SelectValue placeholder={t.agentModelNotConfigured}>
                {selectedDefaultModelConfig ? (
                  <ModelOption
                    config={selectedDefaultModelConfig}
                    notConfiguredLabel={t.agentModelNotConfigured}
                  />
                ) : (
                  t.agentModelNotConfigured
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent
              align="end"
              position="popper"
              sideOffset={4}
            >
              <SelectGroup>
                {agentModelConfigs.map((config) => (
                  <SelectItem key={config.id} value={config.id}>
                    <ModelOption
                      config={config}
                      notConfiguredLabel={t.agentModelNotConfigured}
                    />
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title={t.agentInteractionSettingsTitle}>
        <SettingsRow
          icon={<Languages />}
          label={t.agentResponseLanguage}
          description={t.agentResponseLanguageHint}
        >
          <Select
            value={agentSettings.responseLanguage}
            onValueChange={(value) => {
              if (value === "follow" || value === "zh" || value === "en") {
                onAgentSettingsChange({
                  ...agentSettings,
                  responseLanguage: value,
                });
              }
            }}
          >
            <SelectTrigger
              aria-label={t.agentResponseLanguage}
              className="ml-auto w-auto min-w-44 max-w-full"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectGroup>
                {responseLanguageItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </SettingsRow>
        <Separator className="mx-5 w-auto sm:mx-6" />

        <SettingsRow
          icon={<Gauge />}
          label={t.agentBehavior}
          description={t.agentBehaviorHint}
        >
          <OptionSelect
            label={t.agentBehavior}
            items={behaviorItems}
            value={agentSettings.behaviorMode}
            onChange={(value) =>
              onAgentSettingsChange({
                ...agentSettings,
                behaviorMode: value,
              })
            }
          />
        </SettingsRow>
        <Separator className="mx-5 w-auto sm:mx-6" />

        <SettingsRow
          icon={<ShieldCheck />}
          label={t.agentConfirmationMode}
          description={t.agentConfirmationModeHint}
        >
          <OptionSelect
            label={t.agentConfirmationMode}
            items={confirmationItems}
            value={agentSettings.confirmationMode}
            onChange={(value) =>
              onAgentSettingsChange({
                ...agentSettings,
                confirmationMode: value,
              })
            }
          />
        </SettingsRow>
      </SettingsSection>
    </TabsContent>
  );
}
