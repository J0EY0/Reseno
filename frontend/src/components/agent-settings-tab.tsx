import { Bot, Gauge, Languages, ShieldCheck, SlidersHorizontal } from "lucide-react";

import { ModelProviderIcon } from "@/components/model-provider-icon";
import {
  OptionToggleGroup,
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
    { value: "follow", label: t.followSystemLanguage },
    { value: "zh", label: t.languageChinese },
    { value: "en", label: t.languageEnglish },
  ];
  const selectedDefaultModel =
    modelConfigs.find((config) => config.id === agentSettings.defaultModelId) ??
    null;

  return (
    <TabsContent value="agent" className="mt-5 space-y-5">
      <SettingsSection icon={<Bot />} title={t.agentModelSettingsTitle}>
        <SettingsRow
          icon={<Bot />}
          label={t.defaultAgentModel}
          description={t.defaultAgentModelHint}
        >
          <Select
            value={selectedDefaultModel?.id}
            disabled={modelConfigs.length === 0}
            onValueChange={(value) =>
              onAgentSettingsChange({
                ...agentSettings,
                defaultModelId: value,
              })
            }
          >
            <SelectTrigger
              aria-label={t.defaultAgentModel}
              className="ml-auto w-64 max-w-full"
            >
              <SelectValue placeholder={t.agentModelNotConfigured}>
                {selectedDefaultModel ? (
                  <ModelOption
                    config={selectedDefaultModel}
                    notConfiguredLabel={t.agentModelNotConfigured}
                  />
                ) : (
                  t.agentModelNotConfigured
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent className="min-w-[20rem]">
              <SelectGroup>
                {modelConfigs.map((config) => (
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

      <SettingsSection
        icon={<SlidersHorizontal />}
        title={t.agentInteractionSettingsTitle}
      >
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
              className="ml-auto w-48 max-w-full"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
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
          <OptionToggleGroup
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
          <OptionToggleGroup
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
