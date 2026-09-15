import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { loadMessages, type Locale } from "@/i18n";
import { getAuthSetupStatus, loadAuthSession } from "@/lib/auth";
import { saveLocalePreference } from "@/lib/workspace-storage";

vi.mock("@/lib/auth", () => ({
  clearAuthSession: vi.fn(),
  getAuthSetupStatus: vi.fn(),
  loadAuthSession: vi.fn(),
  loginWithCredentials: vi.fn(),
  refreshAuthSession: vi.fn(),
  setupAuthOwner: vi.fn(),
}));
vi.mock("@/lib/auth-environment", () => ({
  getAuthEnvironmentError: () => null,
}));
vi.mock("@/components/workspace/workspace-preferences", () => ({
  WorkspacePreferencesProvider: ({
    onLocaleChange,
  }: {
    onLocaleChange: (locale: Locale) => Promise<boolean>;
  }) => (
    <>
      <button onClick={() => void onLocaleChange("zh")}>中文</button>
      <button onClick={() => void onLocaleChange("en")}>English</button>
      <Outlet />
    </>
  ),
}));
vi.mock("@/components/workspace/workspace-lateral-layout", () => ({
  WorkspaceLateralLayout: () => <Outlet />,
}));
vi.mock("@/components/workspace/resume-gallery-workspace-page", () => ({
  ResumeGalleryWorkspacePage: () => <h1>Resume gallery</h1>,
}));
vi.mock("@/components/workspace/resume-detail-workspace-page", () => ({
  ResumeDetailWorkspacePage: () => <h1>Resume detail</h1>,
}));
vi.mock("@/components/workspace/template-gallery-workspace-page", () => ({
  TemplateGalleryWorkspacePage: () => <h1>Template gallery</h1>,
}));
vi.mock("@/components/workspace/template-detail-workspace-page", () => ({
  TemplateDetailWorkspacePage: () => <h1>Template detail</h1>,
}));
vi.mock("@/components/workspace/trash-workspace-page", () => ({
  TrashWorkspacePage: () => <h1>Recycle bin</h1>,
}));
vi.mock("@/components/workspace/models-workspace-page", () => ({
  ModelsWorkspacePage: () => <h1>Models</h1>,
}));
vi.mock("@/components/workspace/settings-workspace-page", () => ({
  SettingsWorkspacePage: () => <h1>Settings</h1>,
}));
vi.mock("@/components/auth/login-page", () => ({
  LoginPage: () => <h1>Login</h1>,
}));
vi.mock("@/components/auth/setup-page", () => ({
  SetupPage: () => <h1>Setup</h1>,
}));
vi.mock("@/components/auth/oauth-callback-page", () => ({
  OAuthCallbackPage: () => <h1>OAuth callback</h1>,
}));
vi.mock("@/components/pdf-export-renderer", () => ({
  PdfExportRenderer: () => <h1>PDF renderer</h1>,
}));

function renderApp(pathname: string) {
  const router = createMemoryRouter([{ path: "*", element: <App /> }], {
    initialEntries: [pathname],
  });
  render(<RouterProvider router={router} />);
  return router;
}

async function expectDocumentMetadata(title: string, language = "en") {
  await waitFor(() => {
    expect(document.title).toBe(title);
    expect(document.documentElement.lang).toBe(language);
  });
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  document.title = "Previous page";
  document.documentElement.lang = "";
  vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-US"]);
  vi.mocked(loadAuthSession).mockReturnValue(true);
  vi.mocked(getAuthSetupStatus).mockResolvedValue({
    setupRequired: false,
    githubLoginAvailable: false,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("Unexpected request")),
  );
});

afterEach(() => {
  expect(fetch).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const workspacePages = [
  ["/resume", "Resume gallery", "myResume"],
  ["/resume/example", "Resume detail", "myResume"],
  ["/templates", "Template gallery", "resumeTemplates"],
  ["/template/example", "Template detail", "resumeTemplates"],
  ["/trash", "Recycle bin", "recycleBin"],
  ["/models", "Models", "modelSettings"],
  ["/settings", "Settings", "settings"],
] as const;

describe("Application document metadata", () => {
  it.each(
    workspacePages.flatMap(([path, heading, titleKey]) =>
      [path, `${path}/`].map((pathname) => ({ pathname, heading, titleKey })),
    ),
  )(
    "sets the workspace title at $pathname",
    async ({ pathname, heading, titleKey }) => {
      const messages = await loadMessages("en");
      const router = renderApp(pathname);
      await screen.findByRole("heading", { name: heading });
      expect(router.state.location.pathname).toBe(pathname);
      await expectDocumentMetadata(
        `${messages[titleKey]} · ${messages.brandTitle}`,
      );
    },
  );

  it.each(["en", "zh"] as const)(
    "sets entry-page titles and language using the %s catalog",
    async (locale) => {
      const messages = await loadMessages(locale);
      const language = locale === "zh" ? "zh-CN" : "en";
      saveLocalePreference(locale);
      vi.spyOn(navigator, "languages", "get").mockReturnValue([locale]);
      vi.mocked(loadAuthSession).mockReturnValue(false);
      const router = renderApp("/login");
      await screen.findByRole("heading", { name: "Login" });
      await expectDocumentMetadata(messages.loginTitle, language);

      await act(async () => router.navigate("/pdf-export"));
      await screen.findByRole("heading", { name: "PDF renderer" });
      await expectDocumentMetadata(messages.brandTitle, language);

      await act(async () => router.navigate("/auth/callback"));
      await screen.findByRole("heading", { name: "OAuth callback" });
      await expectDocumentMetadata(messages.brandTitle, language);

      vi.mocked(getAuthSetupStatus).mockResolvedValue({
        setupRequired: true,
        githubLoginAvailable: false,
      });
      await act(async () => router.navigate("/setup"));
      await screen.findByRole("heading", { name: "Setup" });
      await expectDocumentMetadata(messages.setupTitle, language);
    },
  );

  it("updates both title and language when locale changes without leaving the route", async () => {
    const english = await loadMessages("en");
    const chinese = await loadMessages("zh");
    const router = renderApp("/templates");
    await screen.findByRole("heading", { name: "Template gallery" });
    await expectDocumentMetadata(
      `${english.resumeTemplates} · ${english.brandTitle}`,
    );
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    await expectDocumentMetadata(
      `${chinese.resumeTemplates} · ${chinese.brandTitle}`,
      "zh-CN",
    );
    expect(router.state.location.pathname).toBe("/templates");
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    await expectDocumentMetadata(
      `${english.resumeTemplates} · ${english.brandTitle}`,
    );
  });

  it("updates titles when navigating between workspace pages", async () => {
    const messages = await loadMessages("en");
    const router = renderApp("/resume");
    await screen.findByRole("heading", { name: "Resume gallery" });
    await act(async () => router.navigate("/models"));
    await screen.findByRole("heading", { name: "Models" });
    await expectDocumentMetadata(
      `${messages.modelSettings} · ${messages.brandTitle}`,
    );
    await act(async () => router.navigate("/template/example"));
    await screen.findByRole("heading", { name: "Template detail" });
    await expectDocumentMetadata(
      `${messages.resumeTemplates} · ${messages.brandTitle}`,
    );
  });

  it.each(["/unknown", "/templates/example", "/login", "/setup"])(
    "uses the destination title after an authenticated redirect from %s",
    async (pathname) => {
      const messages = await loadMessages("en");
      const router = renderApp(pathname);
      await screen.findByRole("heading", { name: "Resume gallery" });
      expect(router.state.location.pathname).toBe("/resume");
      await expectDocumentMetadata(
        `${messages.myResume} · ${messages.brandTitle}`,
      );
    },
  );
});
