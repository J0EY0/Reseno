import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useTemplateDetailWorkspace } from "@/components/workspace/use-template-detail-workspace";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import {
  createTemplateApi,
  discardTemplateChangesApi,
  fetchTemplateApi,
  fetchWorkspaceRouteData,
  saveDefaultTemplateApi,
  saveTemplateApi,
} from "@/lib/workspace-api";
import {
  createTemplateDetailRouteHandoff,
  getTemplateDetailRouteHandoff,
} from "@/lib/workspace-detail-route-handoff";
import { clearWorkspaceRouteHandoffs } from "@/lib/workspace-route-handoff";
import type {
  TemplateDetailResponse,
  TemplateEditingResponse,
} from "@/types/api";
import { createResumeDetailTemplate } from "./helpers/resume-detail-fixtures";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";

vi.mock("@/lib/workspace-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/workspace-api")>()),
  createTemplateApi: vi.fn(),
  saveTemplateApi: vi.fn(),
  discardTemplateChangesApi: vi.fn(),
  saveDefaultTemplateApi: vi.fn(),
  fetchTemplateApi: vi.fn(),
  fetchWorkspaceRouteData: vi.fn(),
}));
vi.mock("@/components/preview/document-canvas-loader", () => ({
  loadDocumentCanvas: vi.fn(),
}));
vi.mock("@/hooks/use-auth-session-token", () => ({
  useAuthSessionToken: () => "session",
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), dismiss: vi.fn(), error: vi.fn() },
}));

const dispose: (() => void)[] = [];
beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  clearWorkspaceRouteHandoffs();
});
afterEach(() => {
  cleanup();
  dispose.splice(0).forEach((run) => run());
  clearWorkspaceRouteHandoffs();
  vi.useRealTimers();
});
function mount(checkpoint = false) {
  const original = createResumeDetailTemplate("custom-a", {
    name: "Original template",
  });
  const prior = { ...original, description: "Checkpoint description" };
  const defaults = { en: "minimal", zh: "classic" };
  const routeState = createTemplateDetailRouteHandoff(
    original.id,
    {
      customTemplates: [original],
      defaultTemplateIds: defaults,
      checkpoint: checkpoint ? prior : null,
      theme: "light",
    },
    "zh",
  );
  const fixture = createWorkspaceFixture({
    path: `/template/${original.id}`,
    state: routeState,
  });
  dispose.push(() => fixture.router.dispose());
  const logout = vi.fn();
  const hook = renderHook(
    () => ({
      detail: useTemplateDetailWorkspace({
        templateId: original.id,
        routeState,
        locale: "en",
        messages: fixture.preferences.messages,
        onLogout: logout,
      }),
      navigation: useWorkspaceNavigationTransaction(),
    }),
    { wrapper: fixture.wrapper },
  );
  vi.mocked(saveTemplateApi).mockImplementation(async (_id, template) => ({
    template: { ...template, updatedAt: "2026-09-15T00:00:00Z" },
    checkpoint: null,
  }));
  vi.mocked(discardTemplateChangesApi).mockResolvedValue({
    template: checkpoint ? prior : original,
    checkpoint: null,
  });
  vi.mocked(saveDefaultTemplateApi).mockImplementation(
    async (locale, templateId) => ({
      defaultTemplateIds: { ...defaults, [locale]: templateId },
    }),
  );
  return { ...fixture, ...hook, original, prior, defaults, logout };
}
function change(fixture: ReturnType<typeof mount>) {
  act(() =>
    fixture.result.current.detail.updateTemplate(fixture.original.id, {
      description: "Unsaved description",
      settings: { ...fixture.original.settings, bodyColor: "#112233" },
    }),
  );
  expect(fixture.result.current.detail.saveChangeCount).toBeGreaterThan(0);
}

it("saves a dirty source before making one copy and hands its locale, complete catalog and clean checkpoint to the new route", async () => {
  const f = mount();
  expect(f.result.current.detail).toMatchObject({
    hasLoaded: true,
    isLoading: false,
    templateLocale: "zh",
    defaultTemplateId: "classic",
  });
  expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
  expect(fetchTemplateApi).not.toHaveBeenCalled();
  change(f);
  const saved = Promise.withResolvers<TemplateEditingResponse>();
  const created = Promise.withResolvers<TemplateDetailResponse>();
  vi.mocked(saveTemplateApi).mockReturnValueOnce(saved.promise);
  vi.mocked(createTemplateApi).mockReturnValueOnce(created.promise);
  let request!: Promise<void>;
  act(() => {
    request = f.result.current.detail.createCustomTemplate();
  });
  expect(f.result.current.detail.isCreating).toBe(true);
  expect(createTemplateApi).not.toHaveBeenCalled();
  expect(saveTemplateApi).toHaveBeenCalledExactlyOnceWith(
    f.original.id,
    expect.objectContaining({ description: "Unsaved description" }),
    { saveMode: "checkpoint" },
  );
  await act(async () => {
    await f.result.current.detail.createCustomTemplate();
  });
  expect(saveTemplateApi).toHaveBeenCalledTimes(1);
  const source = f.result.current.detail.template!;
  await act(async () => saved.resolve({ template: source, checkpoint: null }));
  expect(createTemplateApi).toHaveBeenCalledOnce();
  expect(createTemplateApi).toHaveBeenCalledWith(
    expect.objectContaining({
      description: "Unsaved description",
      isBuiltIn: false,
      preset: source.preset,
      settings: expect.objectContaining({
        bodyColor: "#112233",
        pagePaddingX: source.settings.pagePaddingX,
      }),
      typography: source.typography,
      layout: source.layout,
    }),
  );
  await act(async () => {
    await f.result.current.detail.createCustomTemplate();
  });
  expect(createTemplateApi).toHaveBeenCalledOnce();
  const copy = createResumeDetailTemplate("copy-b", {
    description: source.description,
    name: "Copied template",
    updatedAt: "2026-09-15T00:00:00Z",
  });
  await act(async () => {
    created.resolve({ template: copy });
    await request;
  });
  expect(f.result.current.detail.isCreating).toBe(false);
  expect(f.result.current.detail.leave.isOpen).toBe(false);
  expect(f.router.state.location.pathname).toBe("/template/copy-b");
  expect(
    getTemplateDetailRouteHandoff(f.router.state.location.state, copy.id),
  ).toMatchObject({
    templateLocale: "zh",
    data: {
      checkpoint: null,
      customTemplates: [source, copy],
      defaultTemplateIds: f.defaults,
      theme: "light",
    },
  });
  expect(toast.success).toHaveBeenCalledExactlyOnceWith(
    f.preferences.messages.templateCreated,
    { closeButton: true },
  );
});

it.each(["logout", "new navigation"] as const)(
  "does not create a copy when %s supersedes its source save",
  async (superseding) => {
    const f = mount();
    change(f);
    const saved = Promise.withResolvers<TemplateEditingResponse>();
    vi.mocked(saveTemplateApi).mockReturnValueOnce(saved.promise);
    let request!: Promise<void>;
    act(() => {
      request = f.result.current.detail.createCustomTemplate();
    });
    act(() => {
      if (superseding === "logout") f.result.current.detail.logout();
      else f.result.current.navigation.beginNavigation();
    });
    await act(async () => {
      saved.resolve({
        template: f.result.current.detail.template!,
        checkpoint: null,
      });
      await request;
    });
    expect(createTemplateApi).not.toHaveBeenCalled();
    expect(f.router.state.location.pathname).toBe("/template/custom-a");
    expect(f.result.current.detail.isCreating).toBe(false);
    expect(toast.success).not.toHaveBeenCalled();
    if (superseding === "logout") {
      expect(f.result.current.detail.leave.isOpen).toBe(true);
      expect(f.logout).not.toHaveBeenCalled();
      act(f.result.current.detail.leave.cancelLeave);
      expect(f.result.current.detail.leave.isOpen).toBe(false);
    }
  },
);

it.each(["logout", "new navigation"] as const)(
  "keeps an already-created copy in the catalog without adopting it or navigating after %s",
  async (superseding) => {
    const f = mount();
    const created = Promise.withResolvers<TemplateDetailResponse>();
    vi.mocked(createTemplateApi).mockReturnValueOnce(created.promise);
    let request!: Promise<void>;
    await act(async () => {
      request = f.result.current.detail.createCustomTemplate();
    });
    expect(createTemplateApi).toHaveBeenCalledOnce();
    act(() => {
      if (superseding === "logout") f.result.current.detail.logout();
      else f.result.current.navigation.beginNavigation();
    });
    const copy = createResumeDetailTemplate("copy-b", {
      updatedAt: "2026-09-15T00:00:00Z",
    });
    await act(async () => {
      created.resolve({ template: copy });
      await request;
    });
    expect(f.result.current.detail.template).toEqual(f.original);
    expect(f.result.current.detail.saveLastSavedAt).toBe(f.original.updatedAt);
    expect(f.result.current.detail.saveChangeCount).toBe(0);
    expect(f.result.current.detail.isCreating).toBe(false);
    expect(f.router.state.location.pathname).toBe("/template/custom-a");
    expect(f.logout).toHaveBeenCalledTimes(superseding === "logout" ? 1 : 0);
    expect(toast.success).not.toHaveBeenCalled();
    await act(() => f.result.current.detail.setDefaultTemplate(copy.id));
    expect(saveDefaultTemplateApi).toHaveBeenCalledExactlyOnceWith(
      "zh",
      copy.id,
    );
    expect(f.result.current.detail.defaultTemplateId).toBe(copy.id);
  },
);

it.each(["cancel", "save", "discard"] as const)(
  "resolves dirty logout through %s while retaining the prepared checkpoint",
  async (decision) => {
    const f = mount(true);
    expect(f.result.current.detail.saveChangeCount).toBe(1);
    act(f.result.current.detail.logout);
    expect(f.result.current.detail.leave.isOpen).toBe(true);
    expect(f.logout).not.toHaveBeenCalled();
    if (decision === "cancel") {
      act(f.result.current.detail.leave.cancelLeave);
      expect(f.result.current.detail.template).toEqual(f.original);
      expect(f.result.current.detail.saveChangeCount).toBe(1);
      expect(f.logout).not.toHaveBeenCalled();
    } else {
      const pending = Promise.withResolvers<TemplateEditingResponse>();
      const operation =
        decision === "save" ? saveTemplateApi : discardTemplateChangesApi;
      vi.mocked(operation).mockReturnValueOnce(pending.promise);
      let request!: Promise<void>;
      act(() => {
        request =
          decision === "save"
            ? f.result.current.detail.leave.saveAndLeave()
            : f.result.current.detail.leave.discardAndLeave();
      });
      expect(f.result.current.detail.leave.isResolving).toBe(true);
      expect(f.logout).not.toHaveBeenCalled();
      if (decision === "save")
        expect(saveTemplateApi).toHaveBeenCalledExactlyOnceWith(
          f.original.id,
          f.original,
          { saveMode: "checkpoint" },
        );
      else
        expect(discardTemplateChangesApi).toHaveBeenCalledExactlyOnceWith(
          f.original.id,
        );
      await act(async () => {
        pending.resolve({
          template: decision === "save" ? f.original : f.prior,
          checkpoint: null,
        });
        await request;
      });
      expect(f.logout).toHaveBeenCalledOnce();
      expect(f.result.current.detail.template).toEqual(
        decision === "save" ? f.original : f.prior,
      );
      expect(f.result.current.detail.saveChangeCount).toBe(0);
    }
    expect(f.result.current.detail.leave.isOpen).toBe(false);
    expect(createTemplateApi).not.toHaveBeenCalled();
    expect(f.router.state.location.pathname).toBe("/template/custom-a");
  },
);
