import type { AgentSettings, ModelConfig } from "@/types/resume";

function createDefaultAgentSettings(
  modelConfigs: readonly Pick<ModelConfig, "id">[] = [],
): AgentSettings {
  return {
    defaultModelConfigId: modelConfigs[0]?.id ?? "",
    responseLanguage: "follow",
    behaviorMode: "balanced",
    confirmationMode: "always",
  };
}

export function normalizeAgentSettings(
  value: unknown,
  modelConfigs: readonly Pick<ModelConfig, "id">[] = [],
): AgentSettings {
  const defaults = createDefaultAgentSettings(modelConfigs);

  if (!value || typeof value !== "object") {
    return defaults;
  }

  const raw = value as Partial<AgentSettings>;
  const rawDefaultModelConfigId =
    typeof raw.defaultModelConfigId === "string"
      ? raw.defaultModelConfigId
      : "";
  const hasDefaultModelConfig = modelConfigs.some(
    (config) => config.id === rawDefaultModelConfigId,
  );

  return {
    defaultModelConfigId: hasDefaultModelConfig
      ? rawDefaultModelConfigId
      : defaults.defaultModelConfigId,
    responseLanguage:
      raw.responseLanguage === "zh" ||
      raw.responseLanguage === "en" ||
      raw.responseLanguage === "follow"
        ? raw.responseLanguage
        : defaults.responseLanguage,
    behaviorMode:
      raw.behaviorMode === "strict" ||
      raw.behaviorMode === "aggressive" ||
      raw.behaviorMode === "balanced"
        ? raw.behaviorMode
        : defaults.behaviorMode,
    confirmationMode:
      raw.confirmationMode === "suggestOnly" ||
      raw.confirmationMode === "always"
        ? raw.confirmationMode
        : defaults.confirmationMode,
  };
}
