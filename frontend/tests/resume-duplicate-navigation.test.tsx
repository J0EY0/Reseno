import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { useResumeDetailWorkspace } from "@/components/workspace/use-resume-detail-workspace";
import { prepareResumeDetailRoute } from "@/components/workspace/workspace-route-preparation";
import { showWorkspaceNavigationError } from "@/components/workspace/workspace-navigation-notifications";
import {
  duplicateResumeApi,
  saveResumeApi,
  fetchResumeVersionsApi,
} from "@/lib/workspace-api";
import {
  createResumeDetailRouteHandoff,
  getResumeDetailRouteHandoff,
} from "@/lib/workspace-detail-route-handoff";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";

vi.mock("@/components/workspace/workspace-route-preparation", () => ({
  prepareResumeDetailRoute: vi.fn(),
  loadResumeDetailRouteData: vi.fn(),
}));
vi.mock("@/components/preview/document-canvas-loader", () => ({
  loadDocumentCanvas: vi.fn(),
}));
vi.mock("@/lib/workspace-api", async (original) => ({
  ...(await original<typeof import("@/lib/workspace-api")>()),
  duplicateResumeApi: vi.fn(),
  saveResumeApi: vi.fn(),
  fetchResumeVersionsApi: vi.fn(),
}));
vi.mock("@/hooks/use-auth-session-token", () => ({
  useAuthSessionToken: () => "session",
}));
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    dismiss: vi.fn(),
  },
}));
vi.mock("@/components/workspace/workspace-navigation-notifications", () => ({
  showWorkspaceNavigationError: vi.fn(),
  clearWorkspaceNavigationError: vi.fn(),
}));
beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false })),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(fetchResumeVersionsApi).mockResolvedValue({ versions: [] });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
function mount() {
  const base = createWorkspaceFixture();
  const initial = createResumeDetailItem();
  const data: PreparedResumeDetailRouteData = {
    detail: { resume: initial, savedAt: "initial", versionId: "v1" },
    routeData: {
      defaultTemplateIds: { en: "minimal", zh: "minimal" },
      customTemplates: [],
      modelConfigs: [],
      agentSettings: base.preferences.agentSettings!,
    },
    versions: [],
  };
  const state = createResumeDetailRouteHandoff(data, 3, 5);
  const fixture = createWorkspaceFixture({ path: "/resume/resume-a", state });
  const onLogout = vi.fn();
  vi.mocked(saveResumeApi).mockImplementation(async (_id, payload) => ({
    resume: { ...initial, ...payload },
    savedAt: "saved",
    versionId: "v2",
  }));
  const copy: PreparedResumeDetailRouteData = {
    ...data,
    detail: {
      ...data.detail,
      resume: createResumeDetailItem({ id: "resume-copy" }),
    },
  };
  vi.mocked(duplicateResumeApi).mockResolvedValue(copy.detail);
  const hook = renderHook(
    () =>
      useResumeDetailWorkspace({
        locale: "en",
        messages: fixture.preferences.messages,
        resumeId: initial.id,
        routeState: state,
        onLogout,
      }),
    { wrapper: fixture.wrapper },
  );
  const commands = () => hook.result.current.model.commands;
  const edit = () =>
    act(() =>
      commands().updateContent((resume) => ({
        ...resume,
        basic: { ...resume.basic, name: "Grace" },
      })),
    );
  async function duplicate() {
    await act(() => commands().duplicateResume());
    const options = vi
      .mocked(toast.success)
      .mock.calls.find(
        ([title]) => title === fixture.preferences.messages.resumeDuplicated,
      )?.[1];
    const action = options?.action;
    if (!action || typeof action !== "object" || !("onClick" in action))
      throw new Error("Missing duplicate action");
    return () => action.onClick({} as React.MouseEvent<HTMLButtonElement>);
  }
  return { ...hook, fixture, copy, commands, edit, duplicate, onLogout };
}
it("creates once, keeps the original open and advances gallery position only when the delayed action is used", async () => {
  const view = mount();
  const gate =
    Promise.withResolvers<Awaited<ReturnType<typeof duplicateResumeApi>>>();
  vi.mocked(duplicateResumeApi).mockReturnValue(gate.promise);
  let action!: Awaited<ReturnType<typeof view.duplicate>>;
  let pending!: Promise<void>;
  act(() => {
    pending = view.duplicate().then((result) => {
      action = result;
    });
  });
  await act(async () => {});
  await act(() => view.commands().duplicateResume());
  expect(duplicateResumeApi).toHaveBeenCalledOnce();
  expect(view.result.current.model.state.isDuplicatingResume).toBe(true);
  await act(async () => {
    gate.resolve(view.copy.detail);
    await pending;
  });
  expect(view.fixture.router.state.location.pathname).toBe("/resume/resume-a");
  expect(prepareResumeDetailRoute).not.toHaveBeenCalled();
  vi.mocked(prepareResumeDetailRoute).mockResolvedValue(view.copy);
  await act(async () => {
    action();
  });
  expect(prepareResumeDetailRoute).toHaveBeenCalledWith(
    "resume-copy",
    view.fixture.persistence,
    { signal: expect.any(AbortSignal) },
  );
  expect(
    getResumeDetailRouteHandoff(
      view.fixture.router.state.location.state,
      "resume-copy",
    ),
  ).toMatchObject({ payload: view.copy, resumeOrdinal: 6, resumeCount: 6 });
});
it("guards the delayed action before reading, then rereads after edits made during preparation", async () => {
  const view = mount();
  const action = await view.duplicate();
  vi.mocked(saveResumeApi).mockClear();
  view.edit();
  act(() => {
    action();
  });
  expect(view.result.current.model.state.leave.isOpen).toBe(true);
  expect(prepareResumeDetailRoute).not.toHaveBeenCalled();
  act(view.commands().cancelLeave);
  expect(view.fixture.router.state.location.pathname).toBe("/resume/resume-a");
  act(() => {
    action();
  });
  const first = Promise.withResolvers<PreparedResumeDetailRouteData>();
  vi.mocked(prepareResumeDetailRoute)
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce(view.copy);
  await act(view.commands().discardAndLeave);
  expect(prepareResumeDetailRoute).toHaveBeenCalledOnce();
  view.edit();
  await act(async () => first.resolve(view.copy));
  expect(view.result.current.model.state.leave.isOpen).toBe(true);
  expect(view.fixture.router.state.location.pathname).toBe("/resume/resume-a");
  await act(view.commands().saveAndLeave);
  expect(saveResumeApi).toHaveBeenCalledOnce();
  expect(vi.mocked(saveResumeApi).mock.calls[0][1].resume.basic.name).toBe(
    "Grace",
  );
  expect(prepareResumeDetailRoute).toHaveBeenCalledTimes(2);
  expect(view.fixture.router.state.location.pathname).toBe(
    "/resume/resume-copy",
  );
});
it.each(["failure", "superseded-success", "superseded-failure"])(
  "keeps the original page after %s",
  async (outcome) => {
    const view = mount();
    const action = await view.duplicate();
    vi.mocked(saveResumeApi).mockClear();
    const gate = Promise.withResolvers<PreparedResumeDetailRouteData>();
    vi.mocked(prepareResumeDetailRoute).mockReturnValue(gate.promise);
    act(() => {
      action();
    });
    const signal = vi.mocked(prepareResumeDetailRoute).mock.calls[0][2].signal;
    if (outcome.startsWith("superseded")) {
      act(view.commands().logout);
      expect(view.onLogout).toHaveBeenCalledOnce();
      expect(signal.aborted).toBe(true);
    }
    await act(async () => {
      if (outcome.endsWith("success")) gate.resolve(view.copy);
      else gate.reject(new Error("Target unavailable"));
    });
    expect(view.fixture.router.state.location.pathname).toBe(
      "/resume/resume-a",
    );
    expect(showWorkspaceNavigationError).toHaveBeenCalledTimes(
      outcome === "failure" ? 1 : 0,
    );
  },
);
it.each(["cancel", "save", "discard"])(
  "resolves dirty logout with %s and supersedes pending duplicate navigation",
  async (resolution) => {
    const view = mount();
    const action = await view.duplicate();
    vi.mocked(saveResumeApi).mockClear();
    const gate = Promise.withResolvers<PreparedResumeDetailRouteData>();
    vi.mocked(prepareResumeDetailRoute).mockReturnValue(gate.promise);
    act(() => {
      action();
    });
    view.edit();
    act(view.commands().logout);
    expect(view.onLogout).not.toHaveBeenCalled();
    expect(view.result.current.model.state.leave.isOpen).toBe(true);
    await act(async () => {
      if (resolution === "cancel") view.commands().cancelLeave();
      else if (resolution === "save") await view.commands().saveAndLeave();
      else await view.commands().discardAndLeave();
    });
    await act(async () => gate.resolve(view.copy));
    expect(view.onLogout).toHaveBeenCalledTimes(
      resolution === "cancel" ? 0 : 1,
    );
    expect(saveResumeApi).toHaveBeenCalledTimes(resolution === "save" ? 1 : 0);
    expect(view.fixture.router.state.location.pathname).toBe(
      "/resume/resume-a",
    );
  },
);
it("uses the selected document ordinal when a blank title has no name", () => {
  const view = mount();
  act(() =>
    view.commands().updateContent((resume) => ({
      ...resume,
      basic: { ...resume.basic, name: "" },
    })),
  );
  act(() => view.commands().changeTitleDraft(" "));
  act(view.commands().saveTitle);
  expect(view.result.current.model.state.resumeItem?.title).toBe(
    "New Resume 3",
  );
});
