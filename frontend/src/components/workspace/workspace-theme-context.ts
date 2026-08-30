import { createContext, useContext } from "react";

import type { AgentSettings, ThemeMode } from "@/types/resume";

export { normalizeWorkspaceTheme } from "@/lib/workspace-theme";

export interface WorkspaceThemeContextValue {
  changeTheme: (theme: ThemeMode, agentSettings?: AgentSettings) => void;
  hydrateTheme: (theme: unknown) => ThemeMode;
  resolvedTheme: "light" | "dark";
  theme: ThemeMode;
}

export const WorkspaceThemeContext =
  createContext<WorkspaceThemeContextValue | null>(null);

export function useWorkspaceTheme() {
  const value = useContext(WorkspaceThemeContext);
  if (!value) {
    throw new Error(
      "useWorkspaceTheme must be used within WorkspaceThemeProvider.",
    );
  }
  return value;
}
