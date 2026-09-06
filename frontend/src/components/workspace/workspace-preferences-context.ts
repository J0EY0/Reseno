import { createContext, useContext } from "react";

import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type { AgentSettings, ModelConfig, ThemeMode } from "@/types/resume";

export interface WorkspacePreferencesContextValue {
  agentSettings: AgentSettings | null;
  changeAgentSettings: (settings: AgentSettings) => void;
  changeLocale: (locale: Locale) => void;
  changeTheme: (theme: ThemeMode) => void;
  locale: Locale;
  messages: AppMessages;
  persistence: WorkspacePreferencesPersistence;
  reconcileModels: (configs: ModelConfig[]) => void;
  resolvedTheme: "light" | "dark";
  theme: ThemeMode;
}

export const WorkspacePreferencesContext =
  createContext<WorkspacePreferencesContextValue | null>(null);

export function useWorkspacePreferences() {
  const value = useContext(WorkspacePreferencesContext);
  if (!value) {
    throw new Error(
      "useWorkspacePreferences must be used within WorkspacePreferencesProvider.",
    );
  }
  return value;
}
