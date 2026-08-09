import type { AppMessages, Locale } from "@/i18n";
import type {
  AgentSettings,
  ModelConfig,
  ThemeMode,
} from "@/types/resume";

export interface SettingsPanelProps {
  locale: Locale;
  t: AppMessages;
  theme: ThemeMode;
  onThemeChange: (value: ThemeMode) => void;
  onLocaleChange: (value: Locale) => void;
  agentSettings: AgentSettings;
  onAgentSettingsChange: (value: AgentSettings) => void;
  modelConfigs: ModelConfig[];
  onPasswordChanged: () => void;
}
