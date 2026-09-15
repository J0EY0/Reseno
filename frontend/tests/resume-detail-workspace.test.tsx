import { act, fireEvent, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useResumeDetailWorkspace } from "@/components/workspace/use-resume-detail-workspace";
import { loadResumeDetailRouteData } from "@/components/workspace/workspace-route-preparation";
import { saveResumeApi, fetchResumeVersionsApi } from "@/lib/workspace-api";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";

vi.mock(
  "@/components/workspace/workspace-route-preparation",
  async (importOriginal) => ({
    ...(await importOriginal<
      typeof import("@/components/workspace/workspace-route-preparation")
    >()),
    loadResumeDetailRouteData: vi.fn(),
  }),
);
vi.mock("@/components/preview/document-canvas-loader", () => ({
  loadDocumentCanvas: vi.fn(),
}));
vi.mock("@/lib/workspace-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/workspace-api")>()),
  saveResumeApi: vi.fn(),
  fetchResumeVersionsApi: vi.fn(),
}));
vi.mock("@/hooks/use-auth-session-token", () => ({
  useAuthSessionToken: () => "session",
}));
vi.mock("@/lib/workspace-load-error", () => ({
  dismissWorkspaceLoadError: vi.fn(),
  showWorkspaceLoadError: vi.fn(),
}));

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false })),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it.each([
  ["loading", true, false, "s", false],
  ["failed", true, false, "s", false],
  ["ready", true, false, "s", true],
  ["ready", false, true, "S", true],
  ["ready", false, false, "s", false],
  ["ready", true, false, "a", false],
] as const)(
  "handles save shortcut for %s with ctrl=%s meta=%s key=%s",
  async (status, ctrlKey, metaKey, key, saves) => {
    const fixture = createWorkspaceFixture({ path: "/resume/resume-a" });
    const initial = createResumeDetailItem();
    const data: PreparedResumeDetailRouteData = {
      detail: { resume: initial, savedAt: "initial", versionId: "v1" },
      routeData: {
        defaultTemplateIds: { en: "minimal", zh: "minimal" },
        customTemplates: [],
        modelConfigs: [],
        agentSettings: fixture.preferences.agentSettings!,
      },
      versions: [],
    };
    const pending = Promise.withResolvers<PreparedResumeDetailRouteData>();
    vi.mocked(loadResumeDetailRouteData).mockReturnValue(pending.promise);
    vi.mocked(saveResumeApi).mockImplementation(async (_id, payload) => ({
      resume: { ...initial, ...payload },
      savedAt: "saved",
      versionId: "v2",
    }));
    vi.mocked(fetchResumeVersionsApi).mockResolvedValue({ versions: [] });
    const hook = renderHook(
      () =>
        useResumeDetailWorkspace({
          locale: "en",
          messages: fixture.preferences.messages,
          resumeId: initial.id,
          routeState: null,
          onLogout: vi.fn(),
        }),
      { wrapper: fixture.wrapper },
    );
    await act(() => vi.advanceTimersByTimeAsync(0));
    if (status === "failed")
      await act(async () => pending.reject(new Error("Load failed")));
    if (status === "ready") {
      await act(async () => pending.resolve(data));
      act(() =>
        hook.result.current.model.commands.updateContent((resume) => ({
          ...resume,
          basic: { ...resume.basic, name: "Grace" },
        })),
      );
    }
    const event = new KeyboardEvent("keydown", {
      ctrlKey,
      metaKey,
      key,
      bubbles: true,
      cancelable: true,
    });
    await act(async () => window.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(
      (ctrlKey || metaKey) && key.toLowerCase() === "s",
    );
    expect(saveResumeApi).toHaveBeenCalledTimes(saves ? 1 : 0);
    if (saves) {
      expect(vi.mocked(saveResumeApi).mock.calls[0][1].resume.basic.name).toBe(
        "Grace",
      );
      expect(hook.result.current.model.state.save.state).toBe("saved");
    }
    hook.unmount();
    fireEvent.keyDown(window, { ctrlKey: true, key: "s" });
    expect(saveResumeApi).toHaveBeenCalledTimes(saves ? 1 : 0);
  },
);
