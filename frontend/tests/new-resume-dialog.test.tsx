import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NewResumeDialog } from "@/components/new-resume-dialog";
import { useResumeGalleryWorkspace } from "@/components/workspace/use-resume-gallery-workspace";
import {
  prepareCreatedResumeDetailRoute,
  preloadResumeDetailRoute,
} from "@/components/workspace/workspace-route-preparation";
import { clearApiCache } from "@/lib/api-client";
import { saveAuthSession } from "@/lib/auth-session";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import {
  createWorkspaceLateralRouteHandoff,
  clearWorkspaceRouteMemory,
} from "@/lib/workspace-route-memory";
import { getMessagesSync, loadMessages } from "@/i18n";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";
import { jsonResponse } from "./helpers/pdf-import-fixtures";

vi.mock(
  "@/components/workspace/workspace-route-preparation",
  async (original) => ({
    ...(await original<
      typeof import("@/components/workspace/workspace-route-preparation")
    >()),
    prepareCreatedResumeDetailRoute: vi.fn(),
    preloadResumeDetailRoute: vi.fn(),
  }),
);
let restore: () => void;
let session = 0;
beforeEach(async () => {
  await loadMessages("zh");
  restore = installPanelBrowserApis();
  clearApiCache();
  clearWorkspaceRouteMemory();
  localStorage.clear();
  saveAuthSession(
    "owner",
    `create-resume-${++session}`,
    "2999-01-01T00:00:00Z",
  );
  vi.mocked(preloadResumeDetailRoute).mockResolvedValue(
    [] as unknown as Awaited<ReturnType<typeof preloadResumeDetailRoute>>,
  );
});
afterEach(() => {
  cleanup();
  restore();
  vi.unstubAllGlobals();
  localStorage.clear();
  clearApiCache();
  clearWorkspaceRouteMemory();
});
it.each(["en", "zh"] as const)(
  "requires an explicit localized language before creating the selected template through the real API: %s",
  async (locale) => {
    const t = getMessagesSync(locale);
    const templates = [
      createResumeDetailTemplate("custom-a"),
      createResumeDetailTemplate("custom-b", {
        settings: {
          ...createResumeDetailTemplate("custom-b").settings,
          pagePaddingX: 18,
        },
      }),
    ];
    const data = {
      resumes: [],
      customTemplates: templates,
      defaultTemplateIds: { en: "custom-a", zh: "custom-a" },
      modelConfigs: [],
      agentSettings: normalizeAgentSettings(null),
    };
    const fixture = createWorkspaceFixture({
      path: "/resume",
      state: createWorkspaceLateralRouteHandoff({ view: "resume", data }),
    });
    const created = {
      resume: createResumeDetailItem({
        id: "created",
        documentLocale: locale,
        template: "custom-b",
      }),
      versionId: "v1",
      savedAt: "2026-09-01T00:00:00Z",
    };
    vi.mocked(prepareCreatedResumeDetailRoute).mockResolvedValue({
      detail: created,
      routeData: data,
      versions: [],
    });
    const fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/api/resumes");
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({
          documentLocale: locale,
          template: "custom-b",
        });
        return jsonResponse(created);
      },
    );
    vi.stubGlobal("fetch", fetch);
    function CreateDialog() {
      const gallery = useResumeGalleryWorkspace({ locale, messages: t });
      return (
        <NewResumeDialog
          disabled={false}
          isCreating={gallery.isCreating}
          messages={t}
          templates={templates}
          defaultTemplateId="custom-a"
          onCreateResume={gallery.createResume}
        />
      );
    }
    render(<CreateDialog />, { wrapper: fixture.wrapper });
    const open = () =>
      fireEvent.click(screen.getByRole("button", { name: t.newResume }));
    open();
    const dialog = screen.getByRole("dialog");
    const language = screen.getByRole("combobox", { name: t.resumeLanguage });
    expect(language.textContent).toBe(t.selectResumeLanguage);
    const submit = within(dialog).getByRole("button", {
      name: t.createResume,
    }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.submit(dialog.querySelector("form")!);
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.keyDown(language, { key: "ArrowDown" });
    fireEvent.click(
      screen.getByRole("option", {
        name: locale === "en" ? t.languageEnglish : t.languageChinese,
      }),
    );
    fireEvent.keyDown(screen.getByRole("combobox", { name: t.template }), {
      key: "ArrowDown",
    });
    fireEvent.click(screen.getByRole("option", { name: "custom-b" }));
    fireEvent.click(within(dialog).getByRole("button", { name: t.cancel }));
    open();
    expect(
      screen.getByRole("combobox", { name: t.resumeLanguage }).textContent,
    ).toBe(t.selectResumeLanguage);
    expect(screen.getByRole("combobox", { name: t.template }).textContent).toBe(
      "custom-a",
    );
    expect(
      (
        within(screen.getByRole("dialog")).getByRole("button", {
          name: t.createResume,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.keyDown(
      screen.getByRole("combobox", { name: t.resumeLanguage }),
      { key: "ArrowDown" },
    );
    fireEvent.click(
      screen.getByRole("option", {
        name: locale === "en" ? t.languageEnglish : t.languageChinese,
      }),
    );
    fireEvent.keyDown(screen.getByRole("combobox", { name: t.template }), {
      key: "ArrowDown",
    });
    fireEvent.click(screen.getByRole("option", { name: "custom-b" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: t.createResume,
      }),
    );
    await waitFor(() =>
      expect(fixture.router.state.location.pathname).toBe("/resume/created"),
    );
    expect(fetch).toHaveBeenCalledOnce();
    expect(prepareCreatedResumeDetailRoute).toHaveBeenCalledOnce();
  },
);
