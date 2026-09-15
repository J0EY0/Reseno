import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { lazy, useState } from "react";
import { ErrorBoundary } from "react-error-boundary";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { AuthSessionErrorBoundary } from "@/components/auth/auth-session-error-boundary";
import en from "@/i18n/locales/en.json";
import { AUTH_SESSION_KEY, saveAuthSession } from "@/lib/auth-session";

vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth")>()),
  getAuthSetupStatus: vi.fn().mockResolvedValue({
    setupRequired: false,
    githubLoginAvailable: false,
  }),
}));
vi.mock("@/lib/auth-environment", () => ({
  getAuthEnvironmentError: () => null,
}));
vi.mock("@/components/workspace/workspace-preferences", () => ({
  WorkspacePreferencesProvider: () => <Outlet />,
}));
vi.mock("@/components/workspace/resume-detail-workspace-page", () => ({
  ResumeDetailWorkspacePage: function Editor() {
    const [value, setValue] = useState("original");
    return (
      <input
        aria-label="Phone"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
    );
  },
}));

afterEach(() => {
  vi.doUnmock("@/components/auth/auth-session-dialog");
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

it("retains route edits after the expired-session chunk fails and removes the notice after cross-tab login", async () => {
  vi.resetModules();
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-US"]);
  const fetch = vi.fn().mockRejectedValue(new Error("Unexpected request"));
  vi.stubGlobal("fetch", fetch);
  const module = Promise.withResolvers<void>();
  const loading = vi.fn();
  vi.doMock("@/components/auth/auth-session-dialog", () => {
    const FailedDialog = lazy(async () => {
      loading();
      await module.promise;
      throw new TypeError(
        "Failed to fetch dynamically imported module: /auth-session.js",
      );
    });
    return { AuthSessionDialog: () => <FailedDialog /> };
  });
  const { default: App } = await import("@/App");
  saveAuthSession("test-owner", "synthetic-token", "2099-01-01T00:00:00Z");
  const router = createMemoryRouter(
    [
      {
        path: "*",
        element: <App />,
        errorElement: <span>Application error</span>,
      },
    ],
    { initialEntries: ["/resume/example"] },
  );
  try {
    render(<RouterProvider router={router} />);
    const phone = await screen.findByRole<HTMLInputElement>("textbox", {
      name: "Phone",
    });
    fireEvent.change(phone, { target: { value: "unsaved" } });
    expect(loading).not.toHaveBeenCalled();
    act(() => {
      window.localStorage.removeItem(AUTH_SESSION_KEY);
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: AUTH_SESSION_KEY,
          storageArea: window.localStorage,
        }),
      );
    });
    await waitFor(() => expect(loading).toHaveBeenCalledOnce());
    await act(async () => module.resolve());
    expect(router.state.errors).toBeNull();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(en.authSessionExpiredDescription)).toBeTruthy();
    const login = screen.getByRole("link", { name: en.authSessionOtherLogin });
    expect(login.getAttribute("href")).toBe("/login");
    expect(login.getAttribute("target")).toBe("_blank");
    expect(login.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByRole("textbox", { name: "Phone" })).toBe(phone);
    expect(phone.value).toBe("unsaved");
    expect(router.state.location.pathname).toBe("/resume/example");
    act(() => {
      saveAuthSession(
        "test-owner",
        "restored-synthetic-token",
        "2099-01-01T00:00:00Z",
      );
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: AUTH_SESSION_KEY,
          storageArea: window.localStorage,
        }),
      );
    });
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByRole("textbox", { name: "Phone" })).toBe(phone);
    expect(phone.value).toBe("unsaved");
    expect(fetch).not.toHaveBeenCalled();
  } finally {
    router.dispose();
  }
});

it("passes non-resource failures to the application boundary", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const failure = new Error("Unexpected authentication render failure");
  const onError = vi.fn();
  function Broken(): never {
    throw failure;
  }
  render(
    <ErrorBoundary fallback={<span>Application error</span>} onError={onError}>
      <AuthSessionErrorBoundary t={en}>
        <Broken />
      </AuthSessionErrorBoundary>
    </ErrorBoundary>,
  );
  expect(screen.getByText("Application error")).toBeTruthy();
  expect(onError.mock.calls[0]?.[0]).toBe(failure);
  expect(
    screen.queryByRole("link", { name: en.authSessionOtherLogin }),
  ).toBeNull();
});
