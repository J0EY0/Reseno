import { act, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import App from "@/App";
import { getMessagesSync } from "@/i18n";
import { clearWorkspaceRouteMemory } from "@/lib/workspace-route-memory";

const mocks = vi.hoisted(() => ({
  ready: false,
  phase: "app",
  page: vi.fn(),
  preferences: vi.fn(),
  route: vi.fn(),
  changeLocale: vi.fn(),
  persistLocale: vi.fn(),
}));
vi.mock("@/hooks/use-auth-gate", () => ({
  useAuthGate: () => ({
    authGate: { phase: mocks.phase },
    login: vi.fn(),
    logout: vi.fn(),
    setup: vi.fn(),
    retry: vi.fn(),
    acceptSession: vi.fn(),
  }),
}));
vi.mock("@/lib/workspace-route-memory", { spy: true });
vi.mock("@/hooks/use-oauth-login", () => ({
  useOAuthLogin: () => ({ isCompleting: false }),
}));
vi.mock("@/lib/preference-api", () => ({
  loadLocalePreferenceApi: () => "en",
  saveLocalePreferenceApi: mocks.persistLocale,
}));
vi.mock("@/i18n/use-locale-messages", () => ({
  useLocaleMessages: () => ({
    locale: "en",
    messages: getMessagesSync("en"),
    isMessagesReady: mocks.ready,
    canPersistLocale: mocks.ready,
    changeLocale: mocks.changeLocale,
  }),
}));
vi.mock("@/components/workspace/workspace-route-loaders", () => ({
  getWorkspaceRouteLoader: mocks.route,
  loadWorkspacePreferencesProvider: mocks.preferences,
  loadModelsWorkspacePage: mocks.page,
  loadResumeDetailWorkspacePage: mocks.page,
  loadResumeGalleryWorkspacePage: mocks.page,
  loadSettingsWorkspacePage: mocks.page,
  loadTemplateDetailWorkspacePage: mocks.page,
  loadTemplateGalleryWorkspacePage: mocks.page,
  loadTrashWorkspacePage: mocks.page,
  loadWorkspaceLateralLayout: mocks.page,
}));

beforeEach(() => {
  vi.resetAllMocks();
  mocks.ready = false;
  mocks.phase = "app";
  mocks.route.mockReturnValue(mocks.page);
});

it("starts the route and shared preferences concurrently while its language catalog is still pending", async () => {
  const page = Promise.withResolvers<unknown>();
  const preferences = Promise.withResolvers<unknown>();
  mocks.page.mockReturnValue(page.promise);
  mocks.preferences.mockReturnValue(preferences.promise);
  render(
    <MemoryRouter initialEntries={["/resume"]}>
      <App />
    </MemoryRouter>,
  );
  expect(mocks.route).toHaveBeenCalledExactlyOnceWith("/resume");
  expect(mocks.page).toHaveBeenCalledOnce();
  expect(mocks.preferences).toHaveBeenCalledOnce();
  expect(mocks.persistLocale).not.toHaveBeenCalled();
  await act(async () => {
    page.resolve({});
    preferences.resolve({});
  });
});

it.each(["loading", "error", "unsupported"])(
  "does not preload private workspace resources during auth %s",
  (phase) => {
    mocks.phase = phase;
    render(
      <MemoryRouter initialEntries={["/resume"]}>
        <App />
      </MemoryRouter>,
    );
    expect(mocks.page).not.toHaveBeenCalled();
    expect(mocks.preferences).not.toHaveBeenCalled();
  },
);

it("contains a rejected prefetch while retaining the catalog loading surface", async () => {
  const error = new Error("Chunk offline");
  const logged = vi.spyOn(console, "error").mockImplementation(() => {});
  mocks.page.mockRejectedValue(error);
  mocks.preferences.mockResolvedValue({});
  const view = render(
    <MemoryRouter initialEntries={["/resume"]}>
      <App />
    </MemoryRouter>,
  );
  await act(async () => {});
  expect(logged).toHaveBeenCalledWith(
    "Failed to preload the current application route.",
    error,
  );
  expect(view.getByRole("status", { name: "Loading" })).not.toBeNull();
});

it("clears route snapshots once when leaving the authenticated app", async () => {
  mocks.page.mockResolvedValue({});
  mocks.preferences.mockResolvedValue({});
  const view = render(
    <MemoryRouter initialEntries={["/resume"]}>
      <App />
    </MemoryRouter>,
  );
  expect(clearWorkspaceRouteMemory).not.toHaveBeenCalled();
  mocks.phase = "loading";
  await act(async () =>
    view.rerender(
      <MemoryRouter initialEntries={["/resume"]}>
        <App />
      </MemoryRouter>,
    ),
  );
  await vi.waitFor(() =>
    expect(clearWorkspaceRouteMemory).toHaveBeenCalledOnce(),
  );
  mocks.phase = "error";
  await act(async () =>
    view.rerender(
      <MemoryRouter initialEntries={["/resume"]}>
        <App />
      </MemoryRouter>,
    ),
  );
  expect(clearWorkspaceRouteMemory).toHaveBeenCalledOnce();
});
