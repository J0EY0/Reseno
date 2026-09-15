import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useResumeGalleryWorkspace } from "@/components/workspace/use-resume-gallery-workspace";
import { useTemplateGalleryWorkspace } from "@/components/workspace/use-template-gallery-workspace";
import { useTrashWorkspace } from "@/components/workspace/use-trash-workspace";
import { useTemplateDetailWorkspace } from "@/components/workspace/use-template-detail-workspace";
import { useWorkspacePreferencesRoute } from "@/components/workspace/use-workspace-preferences-route";
import { fetchWorkspaceRouteData, fetchTemplateApi } from "@/lib/workspace-api";
import {
  dismissWorkspaceLoadError,
  showWorkspaceLoadError,
} from "@/lib/workspace-load-error";
import {
  clearWorkspaceRouteMemory,
  createWorkspaceLateralRouteHandoff,
} from "@/lib/workspace-route-memory";
import type { WorkspaceRouteDataResult } from "@/lib/workspace-route-data";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import { createTemplateDetailRouteHandoff } from "@/lib/workspace-detail-route-handoff";

vi.mock("@/lib/workspace-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/workspace-api")>()),
  fetchWorkspaceRouteData: vi.fn(),
  fetchTemplateApi: vi.fn(),
}));
vi.mock("@/components/preview/document-canvas-loader", () => ({
  loadDocumentCanvas: vi.fn(),
}));
vi.mock("@/lib/workspace-load-error", () => ({
  dismissWorkspaceLoadError: vi.fn(),
  showWorkspaceLoadError: vi.fn(),
}));
vi.mock("@/hooks/use-auth-session-token", () => ({
  useAuthSessionToken: () => "session",
}));

const data = {
  defaultTemplateIds: { en: "minimal", zh: "minimal" },
  customTemplates: [createResumeDetailTemplate("custom-a")],
  resumes: [createResumeDetailItem()],
  deletedResumes: [],
  deletedTemplates: [],
};
const routes = [
  {
    kind: "resume-gallery",
    view: "resume",
    path: "/resume",
    hook: useResumeGalleryWorkspace,
  },
  {
    kind: "template-gallery",
    view: "templates",
    path: "/templates",
    hook: useTemplateGalleryWorkspace,
  },
  { kind: "trash", view: "trash", path: "/trash", hook: useTrashWorkspace },
] as const;

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  clearWorkspaceRouteMemory();
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => vi.useRealTimers());
const start = () => act(() => vi.advanceTimersByTimeAsync(0));

describe.each(routes)(
  "$kind lifecycle",
  ({ kind, view, path, hook: useRoute }) => {
    function mount(state: unknown = null) {
      const fixture = createWorkspaceFixture({ path, state });
      return {
        ...fixture,
        ...renderHook(
          () =>
            useRoute({ locale: "en", messages: fixture.preferences.messages }),
          { wrapper: fixture.wrapper },
        ),
      };
    }
    it("consumes prepared data without a StrictMode request or preference write", () => {
      const fixture = mount(createWorkspaceLateralRouteHandoff({ view, data }));
      expect(fixture.result.current).toMatchObject({
        hasLoaded: true,
        hasLoadError: false,
      });
      expect(fixture.result.current.routeData).toMatchObject({
        customTemplates: data.customTemplates,
      });
      expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    });
    it("starts one request, shows a failure, then accepts a successful retry", async () => {
      const error = new Error("Route unavailable");
      vi.mocked(fetchWorkspaceRouteData)
        .mockRejectedValueOnce(error)
        .mockResolvedValueOnce({ kind, data });
      const fixture = mount();
      await start();
      expect(fetchWorkspaceRouteData).toHaveBeenCalledOnce();
      expect(fixture.result.current).toMatchObject({
        hasLoaded: false,
        hasLoadError: true,
      });
      expect(showWorkspaceLoadError).toHaveBeenCalledExactlyOnceWith(
        error,
        fixture.preferences.messages.apiMessages.REQUEST_FAILED,
      );
      act(fixture.result.current.retryLoad);
      await start();
      expect(fetchWorkspaceRouteData).toHaveBeenCalledTimes(2);
      expect(dismissWorkspaceLoadError).toHaveBeenCalledTimes(2);
      expect(fixture.result.current).toMatchObject({
        hasLoaded: true,
        hasLoadError: false,
      });
      expect(fixture.result.current.routeData.customTemplates).toEqual(
        data.customTemplates,
      );
      expect(vi.mocked(fetchWorkspaceRouteData).mock.calls[1]).toEqual([
        kind,
        { signal: expect.any(AbortSignal), notifyOnError: false },
      ]);
    });
    it.each(["success", "failure"])(
      "aborts on unmount and ignores a late %s",
      async (outcome) => {
        const pending = Promise.withResolvers<WorkspaceRouteDataResult>();
        vi.mocked(fetchWorkspaceRouteData).mockReturnValue(pending.promise);
        const fixture = mount();
        await start();
        const signal = vi.mocked(fetchWorkspaceRouteData).mock.calls[0][1]!
          .signal!;
        fixture.unmount();
        expect(signal.aborted).toBe(true);
        await act(async () =>
          outcome === "success"
            ? pending.resolve({ kind, data })
            : pending.reject(new DOMException("Cancelled", "AbortError")),
        );
        expect(showWorkspaceLoadError).not.toHaveBeenCalled();
      },
    );
    it("sends no request if unmounted before the scheduled load", async () => {
      mount().unmount();
      await start();
      expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    });
  },
);

it("retries template-detail transport and validates the target before exposing an editor", async () => {
  const fixture = createWorkspaceFixture({ path: "/template/custom-a" });
  const error = new Error("Template unavailable");
  vi.mocked(fetchWorkspaceRouteData)
    .mockRejectedValueOnce(error)
    .mockResolvedValue({ kind: "template-detail", data });
  const template = data.customTemplates[0];
  vi.mocked(fetchTemplateApi).mockResolvedValue({
    template,
    checkpoint: template,
  });
  const hook = renderHook(
    () =>
      useTemplateDetailWorkspace({
        locale: "en",
        messages: fixture.preferences.messages,
        onLogout: vi.fn(),
        routeState: null,
        templateId: "custom-a",
      }),
    { wrapper: fixture.wrapper },
  );
  await start();
  expect(hook.result.current).toMatchObject({
    hasLoadError: true,
    hasLoaded: false,
  });
  expect(showWorkspaceLoadError).toHaveBeenCalledExactlyOnceWith(
    error,
    fixture.preferences.messages.apiMessages.REQUEST_FAILED,
  );
  act(hook.result.current.retryLoad);
  await start();
  expect(hook.result.current).toMatchObject({
    hasLoadError: false,
    hasLoaded: true,
  });
  expect(hook.result.current.template?.id).toBe("custom-a");
  expect(fetchWorkspaceRouteData).toHaveBeenCalledTimes(2);
});

it("opens a prepared template immediately with its document language and checkpoint without any read", async () => {
  const template = data.customTemplates[0];
  const fixture = createWorkspaceFixture({ path: "/template/custom-a" });
  const routeState = createTemplateDetailRouteHandoff(
    template.id,
    { ...data, checkpoint: template },
    "zh",
  );
  const hook = renderHook(
    () =>
      useTemplateDetailWorkspace({
        locale: "en",
        messages: fixture.preferences.messages,
        onLogout: vi.fn(),
        routeState,
        templateId: template.id,
      }),
    { wrapper: fixture.wrapper },
  );
  expect(hook.result.current).toMatchObject({
    hasLoaded: true,
    hasLoadError: false,
    templateLocale: "zh",
    template,
  });
  await start();
  expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
  expect(fetchTemplateApi).not.toHaveBeenCalled();
});

it("does not expose an editor when the requested template is missing from the validated catalog", async () => {
  const fixture = createWorkspaceFixture({ path: "/template/missing" });
  vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
    kind: "template-detail",
    data,
  });
  vi.mocked(fetchTemplateApi).mockResolvedValue({
    template: createResumeDetailTemplate("missing"),
    checkpoint: null,
  });
  const hook = renderHook(
    () =>
      useTemplateDetailWorkspace({
        locale: "en",
        messages: fixture.preferences.messages,
        onLogout: vi.fn(),
        routeState: null,
        templateId: "missing",
      }),
    { wrapper: fixture.wrapper },
  );
  await start();
  expect(hook.result.current).toMatchObject({
    hasLoaded: false,
    hasLoadError: true,
    template: null,
  });
  expect(showWorkspaceLoadError).toHaveBeenCalledOnce();
});

describe.each(["models", "settings"] as const)(
  "%s preference route",
  (kind) => {
    const routeData = {
      agentSettings: normalizeAgentSettings(null),
      modelConfigs: [],
    };
    it.each([true, false])(
      "skips transport only when shared Agent preferences are present: %s",
      async (complete) => {
        const fixture = createWorkspaceFixture({
          path: `/${kind}`,
          state: createWorkspaceLateralRouteHandoff({
            view: kind,
            data: routeData,
          }),
        });
        if (!complete) fixture.preferences.agentSettings = null;
        vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
          kind,
          data: routeData,
        });
        const hook = renderHook(
          () => useWorkspacePreferencesRoute({ kind, locale: "en" }),
          { wrapper: fixture.wrapper },
        );
        expect(hook.result.current.hasLoaded).toBe(complete);
        await start();
        expect(fetchWorkspaceRouteData).toHaveBeenCalledTimes(complete ? 0 : 1);
        if (!complete) {
          expect(hook.result.current.hasLoaded).toBe(false);
          fixture.preferences.agentSettings = routeData.agentSettings;
          hook.rerender();
        }
        expect(hook.result.current.hasLoaded).toBe(true);
      },
    );
    it("shows one failure, retries and cancels a superseded read", async () => {
      const fixture = createWorkspaceFixture({ path: `/${kind}` });
      const old = Promise.withResolvers<WorkspaceRouteDataResult>();
      const error = new Error("Preferences unavailable");
      vi.mocked(fetchWorkspaceRouteData)
        .mockReturnValueOnce(old.promise)
        .mockRejectedValueOnce(error)
        .mockResolvedValueOnce({ kind, data: routeData });
      const hook = renderHook(
        () => useWorkspacePreferencesRoute({ kind, locale: "en" }),
        { wrapper: fixture.wrapper },
      );
      await start();
      const oldSignal = vi.mocked(fetchWorkspaceRouteData).mock.calls[0][1]!
        .signal!;
      act(hook.result.current.retryLoad);
      await start();
      expect(oldSignal.aborted).toBe(true);
      expect(hook.result.current).toMatchObject({
        hasLoadError: true,
        hasLoaded: false,
      });
      await act(async () => old.reject(new Error("Stale failure")));
      expect(showWorkspaceLoadError).toHaveBeenCalledExactlyOnceWith(
        error,
        fixture.preferences.messages.apiMessages.REQUEST_FAILED,
      );
      act(hook.result.current.retryLoad);
      await start();
      expect(hook.result.current).toMatchObject({
        hasLoadError: false,
        hasLoaded: true,
      });
      expect(fetchWorkspaceRouteData).toHaveBeenCalledTimes(3);
    });
  },
);
