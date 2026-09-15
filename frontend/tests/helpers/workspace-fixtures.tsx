import {
  StrictMode,
  createContext,
  useContext,
  type ContextType,
  type ReactNode,
} from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { WorkspacePreferencesContext } from "@/components/workspace/workspace-preferences-context";
import { getMessagesSync } from "@/i18n";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import { createWorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function createWorkspaceFixture({
  path = "/resume",
  state = null as unknown,
} = {}) {
  const agentSettings = normalizeAgentSettings(null);
  const persistence = createWorkspacePreferencesPersistence(
    { locale: "en", theme: "light", agentSettings },
    {
      onChange: vi.fn(),
      onError: vi.fn(),
      save: vi.fn(async (patch) => patch),
    },
  );
  const preferences: NonNullable<
    ContextType<typeof WorkspacePreferencesContext>
  > = {
    agentSettings,
    persistence,
    locale: "en",
    messages: getMessagesSync("en"),
    theme: "light",
    resolvedTheme: "light",
    changeAgentSettings: vi.fn(),
    changeLocale: vi.fn(),
    changeTheme: vi.fn(),
    reconcileModels: vi.fn(),
  };
  const SlotContext = createContext<ReactNode>(null);
  function Slot() {
    return useContext(SlotContext);
  }
  const router = createMemoryRouter([{ path: "*", element: <Slot /> }], {
    initialEntries: [{ pathname: path, state }],
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <StrictMode>
        <WorkspacePreferencesContext value={preferences}>
          <SlotContext value={children}>
            <RouterProvider router={router} />
          </SlotContext>
        </WorkspacePreferencesContext>
      </StrictMode>
    );
  }
  return {
    preferences,
    persistence,
    wrapper: Wrapper,
    get router() {
      return router;
    },
  };
}
