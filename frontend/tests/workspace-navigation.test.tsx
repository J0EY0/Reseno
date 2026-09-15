import { StrictMode, createContext, useContext, type ReactNode } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { toast } from "sonner";
import { readWorkspaceHandoffToken } from "@/lib/workspace-route-handoff";
import * as handoffs from "@/lib/workspace-route-handoff";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspacePreferencesContext } from "@/components/workspace/workspace-preferences-context";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import { usePreparedWorkspaceNavigation } from "@/components/workspace/use-prepared-workspace-navigation";
import { useResumeDetailLeave } from "@/components/workspace/use-resume-detail-leave";
import { preloadWorkspaceRoute } from "@/components/workspace/workspace-route-loaders";
import { showWorkspaceNavigationError } from "@/components/workspace/workspace-navigation-notifications";
import { fetchWorkspaceRouteData } from "@/lib/workspace-api";
import {
  clearWorkspaceRouteMemory,
  getWorkspaceLateralRouteHandoff,
} from "@/lib/workspace-route-memory";
import { createWorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type { WorkspaceRouteDataResult } from "@/lib/workspace-route-data";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";

vi.mock("@/components/workspace/workspace-route-loaders", () => ({
  preloadWorkspaceRoute: vi.fn(),
}));
vi.mock("@/lib/workspace-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/workspace-api")>()),
  fetchWorkspaceRouteData: vi.fn(),
}));
vi.mock("@/components/workspace/workspace-navigation-notifications", () => ({
  clearWorkspaceNavigationError: vi.fn(),
  showWorkspaceNavigationError: vi.fn(),
}));

function deferred<T>() {
  return Promise.withResolvers<T>();
}
const disposers: (() => void)[] = [];
function fixture(path = "/resume/detail") {
  window.history.replaceState({ key: "navigation-test", idx: 0 }, "", path);
  const base = createWorkspaceFixture();
  base.router.dispose();
  const SlotContext = createContext<ReactNode>(null);
  function Slot() {
    return useContext(SlotContext);
  }
  const router = createBrowserRouter([{ path: "*", element: <Slot /> }]);
  disposers.push(() => router.dispose());
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <StrictMode>
        <WorkspacePreferencesContext value={base.preferences}>
          <SlotContext value={children}>
            <RouterProvider router={router} />
          </SlotContext>
        </WorkspacePreferencesContext>
      </StrictMode>
    );
  }
  return { ...base, router, wrapper: Wrapper };
}
function templates(
  theme: "light" | "dark" = "light",
): WorkspaceRouteDataResult<"template-gallery"> {
  return {
    kind: "template-gallery",
    data: {
      theme,
      customTemplates: [],
      defaultTemplateIds: { en: "modern", zh: "modern" },
    },
  };
}
function setupPrepared() {
  const f = fixture();
  const allocateHandoff = vi.spyOn(handoffs, "createWorkspaceHandoffToken");
  const requestLeave = vi.fn((run: () => void, _cancel?: () => void) => {
    void _cancel;
    run();
  });
  const requiresLeaveResolution = vi.fn(() => false);
  const hook = renderHook(
    () =>
      usePreparedWorkspaceNavigation({
        persistence: f.persistence,
        preparationErrorMessage: "Preparation failed",
        requestLeave,
        requiresLeaveResolution,
      }),
    { wrapper: f.wrapper },
  );
  return {
    ...f,
    ...hook,
    requestLeave,
    requiresLeaveResolution,
    allocateHandoff,
  };
}

beforeEach(() => {
  vi.mocked(preloadWorkspaceRoute).mockResolvedValue([
    { default: () => <></> },
    { default: () => <></> },
    { default: () => <></> },
  ]);
  vi.spyOn(toast, "warning").mockReturnValue(0);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "matchMedia",
    vi.fn((media: string) => ({
      media,
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    })),
  );
});
afterEach(() => {
  cleanup();
  disposers.splice(0).forEach((dispose) => dispose());
  clearWorkspaceRouteMemory();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

describe("workspace navigation ownership", () => {
  it("shares the latest intent across owners, with guarded stale cancel and finish", () => {
    const f = fixture();
    const first = renderHook(useWorkspaceNavigationTransaction, {
      wrapper: f.wrapper,
    });
    // A distinct router owner shares the transaction without sharing hook state.
    const other = fixture();
    const second = renderHook(useWorkspaceNavigationTransaction, {
      wrapper: other.wrapper,
    });
    const old = first.result.current.beginNavigation();
    const current = second.result.current.beginNavigation();
    expect(old.signal.aborted).toBe(true);
    expect(old.isCurrent()).toBe(false);
    old.cancel();
    old.finish();
    first.unmount();
    expect(current.signal.aborted).toBe(false);
    expect(current.isCurrent()).toBe(true);
    current.finish();
    expect(current.isCurrent()).toBe(false);
    expect(current.signal.aborted).toBe(false);
    const next = second.result.current.beginNavigation();
    current.cancel();
    expect(next.isCurrent()).toBe(true);
    second.result.current.cancelNavigation();
    expect(next.signal.aborted).toBe(true);
    expect(next.isCurrent()).toBe(false);
  });

  it("aborts the still-current intent when its owner unmounts", () => {
    const f = fixture();
    const { result, unmount } = renderHook(useWorkspaceNavigationTransaction, {
      wrapper: f.wrapper,
    });
    const intent = result.current.beginNavigation();
    unmount();
    expect(intent.signal.aborted).toBe(true);
    expect(intent.isCurrent()).toBe(false);
  });

  it.each(["query PUSH", "query POP"] as const)(
    "supersedes a pending intent on %s without unmounting its owner",
    async (navigation) => {
      const f = fixture();
      const { result } = renderHook(useWorkspaceNavigationTransaction, {
        wrapper: f.wrapper,
      });
      await act(() => f.router.navigate("?page=2"));
      const begin = result.current.beginNavigation;
      const intent = begin();
      const key = window.history.state.key;
      if (navigation === "query PUSH")
        await act(() => f.router.navigate("?page=3"));
      else {
        await act(async () => {
          await f.router.navigate(-1);
        });
        await waitFor(() => expect(f.router.state.location.search).toBe(""));
      }
      expect(window.history.state.key).not.toBe(key);
      expect(result.current.beginNavigation).toBe(begin);
      expect(intent.signal.aborted).toBe(true);
      expect(intent.isCurrent()).toBe(false);
    },
  );
});

describe("prepared detail navigation", () => {
  it("preloads only modules and ignores a hover loading failure", async () => {
    const f = setupPrepared();
    const flush = vi.spyOn(f.persistence, "flush");
    vi.mocked(preloadWorkspaceRoute).mockRejectedValueOnce(
      new Error("chunk offline"),
    );
    await act(async () => f.result.current.preload("templates"));
    expect(preloadWorkspaceRoute).toHaveBeenCalledExactlyOnceWith("templates");
    expect(flush).not.toHaveBeenCalled();
    expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    expect(f.requestLeave).not.toHaveBeenCalled();
    expect(showWorkspaceNavigationError).not.toHaveBeenCalled();
  });

  it("resolves the draft before flushing preferences, fetching fresh data, and creating a handoff", async () => {
    const f = fixture();
    const requestLeave = vi.fn((_run: () => void, _cancel?: () => void) => {
      void _run;
      void _cancel;
    });
    const preferenceSave = deferred<{ theme: "dark" }>();
    const save = vi.fn(() => preferenceSave.promise);
    const persistence = createWorkspacePreferencesPersistence(
      f.persistence.getSnapshot(),
      { save, onChange: vi.fn(), onError: vi.fn() },
    );
    const { result } = renderHook(
      () =>
        usePreparedWorkspaceNavigation({
          persistence,
          preparationErrorMessage: "Preparation failed",
          requestLeave: requestLeave,
          requiresLeaveResolution: () => false,
        }),
      { wrapper: f.wrapper },
    );
    const guards: (() => void)[] = [];
    requestLeave.mockImplementation((run) => {
      guards.push(run);
    });
    const data = templates("dark");
    vi.mocked(fetchWorkspaceRouteData).mockResolvedValue(data);
    act(() => {
      persistence.change({ theme: "dark" });
      result.current.request("templates");
    });
    expect(preloadWorkspaceRoute).not.toHaveBeenCalled();
    expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    expect(f.router.state.location.pathname).toBe("/resume/detail");
    await act(async () => {
      guards[0]();
    });
    expect(preloadWorkspaceRoute).toHaveBeenCalledExactlyOnceWith("templates");
    expect(save).toHaveBeenCalledExactlyOnceWith({ theme: "dark" }, "en");
    expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    await act(async () => {
      preferenceSave.resolve({ theme: "dark" });
    });
    expect(fetchWorkspaceRouteData).toHaveBeenCalledExactlyOnceWith(
      "template-gallery",
      { notifyOnError: false, signal: expect.any(AbortSignal) },
    );
    expect(f.router.state.location.pathname).toBe("/templates");
    expect(
      getWorkspaceLateralRouteHandoff(f.router.state.location.state),
    ).toEqual({ view: "templates", data: data.data });
    expect(
      getWorkspaceLateralRouteHandoff(f.router.state.location.state)?.data,
    ).toBe(data.data);
  });

  it("re-enters the leave guard after a late edit and prepares again after resolution", async () => {
    const f = setupPrepared();
    const oldRead = deferred<WorkspaceRouteDataResult>();
    const freshRead = deferred<WorkspaceRouteDataResult>();
    vi.mocked(fetchWorkspaceRouteData)
      .mockReturnValueOnce(oldRead.promise)
      .mockReturnValueOnce(freshRead.promise);
    await act(async () => f.result.current.request("templates"));
    f.requiresLeaveResolution.mockReturnValue(true);
    let continueLeave: (() => void) | undefined;
    f.requestLeave.mockImplementation((run) => {
      continueLeave = run;
    });
    await act(async () => {
      oldRead.resolve(templates());
    });
    expect(f.requestLeave).toHaveBeenCalledTimes(2);
    expect(f.router.state.location.state).toBeNull();
    expect(f.allocateHandoff).not.toHaveBeenCalled();
    expect(f.router.state.location.pathname).toBe("/resume/detail");
    f.requiresLeaveResolution.mockReturnValue(false);
    await act(async () => continueLeave!());
    expect(fetchWorkspaceRouteData).toHaveBeenCalledTimes(2);
    expect(preloadWorkspaceRoute).toHaveBeenCalledTimes(2);
    const latest = templates("dark");
    await act(async () => {
      freshRead.resolve(latest);
    });
    expect(
      getWorkspaceLateralRouteHandoff(f.router.state.location.state)?.data,
    ).toBe(latest.data);
  });

  it.each(
    ["cancel", "unmount", "new intent"].flatMap((reason) =>
      ["resolve", "reject"].map((settlement) => ({ reason, settlement })),
    ),
  )(
    "does not commit or notify for a late $settlement after $reason",
    async ({ reason, settlement }) => {
      const f = setupPrepared();
      const oldRead = deferred<WorkspaceRouteDataResult>();
      vi.mocked(fetchWorkspaceRouteData).mockReturnValueOnce(oldRead.promise);
      await act(async () => f.result.current.request("templates"));
      const signal = vi.mocked(fetchWorkspaceRouteData).mock.calls[0][1]!
        .signal!;
      if (reason === "cancel") act(() => f.result.current.cancelPending());
      if (reason === "unmount") f.unmount();
      if (reason === "new intent") {
        f.requestLeave.mockImplementation(() => undefined);
        act(() => f.result.current.request("settings"));
      }
      expect(signal.aborted).toBe(true);
      await act(async () => {
        if (settlement === "resolve") oldRead.resolve(templates());
        else oldRead.reject(new Error("late offline"));
      });
      expect(f.router.state.location.pathname).toBe("/resume/detail");
      expect(f.router.state.location.state).toBeNull();
      expect(f.allocateHandoff).not.toHaveBeenCalled();
      expect(showWorkspaceNavigationError).not.toHaveBeenCalled();
    },
  );

  it("canceling the first leave guard prevents any preparation", async () => {
    const f = setupPrepared();
    let resume: (() => void) | undefined;
    f.requestLeave.mockImplementation((run, cancel) => {
      resume = run;
      cancel?.();
    });
    await act(async () => {
      f.result.current.request("templates");
      resume!();
    });
    expect(preloadWorkspaceRoute).not.toHaveBeenCalled();
    expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    expect(f.allocateHandoff).not.toHaveBeenCalled();
  });

  it.each(["fetch failure", "module failure", "abort"] as const)(
    "keeps the current route on %s",
    async (failure) => {
      const f = setupPrepared();
      const error =
        failure === "abort"
          ? new DOMException("Aborted", "AbortError")
          : new Error("offline");
      const logged = vi
        .spyOn(console, "error")
        .mockImplementation(() => undefined);
      if (failure === "module failure") {
        vi.mocked(preloadWorkspaceRoute).mockRejectedValueOnce(error);
        vi.mocked(fetchWorkspaceRouteData).mockResolvedValue(templates());
      } else vi.mocked(fetchWorkspaceRouteData).mockRejectedValueOnce(error);
      await act(async () => f.result.current.request("templates"));
      expect(f.router.state.location.pathname).toBe("/resume/detail");
      expect(f.router.state.location.state).toBeNull();
      expect(showWorkspaceNavigationError).toHaveBeenCalledTimes(
        failure === "abort" ? 0 : 1,
      );
      if (failure !== "abort") {
        expect(showWorkspaceNavigationError).toHaveBeenCalledWith(
          "Preparation failed",
        );
        expect(logged).toHaveBeenCalledWith(
          "Failed to prepare the workspace route.",
          error,
        );
      }
    },
  );

  it("deletes the allocated handoff when browser history rejects the final commit", async () => {
    const f = setupPrepared();
    vi.mocked(fetchWorkspaceRouteData).mockResolvedValue(templates());
    const error = new DOMException(
      "History cannot clone this navigation",
      "DataCloneError",
    );
    const push = vi
      .spyOn(window.history, "pushState")
      .mockImplementation(() => {
        throw error;
      });
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    await act(async () => f.result.current.request("templates"));
    const state = push.mock.calls[0][0] as { usr: { token: string } };
    expect(state.usr.token).toEqual(expect.any(String));
    expect(readWorkspaceHandoffToken(state.usr.token)).toBeUndefined();
    expect(showWorkspaceNavigationError).toHaveBeenCalledExactlyOnceWith(
      "Preparation failed",
    );
    expect(f.router.state.location.pathname).toBe("/resume/detail");
  });

  it.each(["success", "history-only failure"] as const)(
    "awaits one shared checkpoint promotion and honors the latest destination after %s",
    async (outcome) => {
      const f = fixture();
      let needsPromotion = true;
      const promotion = deferred<void>();
      const promoteCheckpoint = vi.fn(() =>
        promotion.promise.then(() => {
          needsPromotion = false;
        }),
      );
      const markCheckpointPromotionSkipped = vi.fn(() => {
        needsPromotion = false;
      });
      vi.spyOn(console, "warn").mockImplementation(() => undefined);
      const { result } = renderHook(
        () => {
          const leave = useResumeDetailLeave({
            discard: vi.fn(),
            save: vi.fn(),
            hasUnsavedChanges: () => false,
            requiresCheckpointPromotion: () => needsPromotion,
            promoteCheckpoint,
            markCheckpointPromotionSkipped,
            messages: f.preferences.messages,
          });
          return usePreparedWorkspaceNavigation({
            persistence: f.persistence,
            preparationErrorMessage: "Preparation failed",
            requestLeave: leave.requestLeave,
            requiresLeaveResolution: () => needsPromotion,
          });
        },
        { wrapper: f.wrapper },
      );
      vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
        kind: "settings",
        data: { modelConfigs: [], agentSettings: f.preferences.agentSettings! },
      });
      act(() => {
        result.current.request("templates");
        result.current.request("settings");
      });
      expect(promoteCheckpoint).toHaveBeenCalledTimes(1);
      expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
      await act(async () => {
        if (outcome === "success") promotion.resolve();
        else promotion.reject(new Error("checkpoint offline"));
      });
      expect(fetchWorkspaceRouteData).toHaveBeenCalledExactlyOnceWith(
        "settings",
        { notifyOnError: false, signal: expect.any(AbortSignal) },
      );
      expect(f.router.state.location.pathname).toBe("/settings");
      expect(
        getWorkspaceLateralRouteHandoff(f.router.state.location.state)?.view,
      ).toBe("settings");
      expect(markCheckpointPromotionSkipped).toHaveBeenCalledTimes(
        outcome === "success" ? 0 : 1,
      );
    },
  );
});

describe("workspace sidebar navigation", () => {
  function setupShell() {
    const f = fixture("/resume");
    const onLogout = vi.fn();
    render(
      <WorkspaceShell activeView="resume" onLogout={onLogout}>
        <p>Current gallery</p>
      </WorkspaceShell>,
      { wrapper: f.wrapper },
    );
    return { ...f, onLogout };
  }

  it.each(["focus", "hover"] as const)(
    "%s preloads the destination without reading data or saving preferences",
    async (event) => {
      const f = setupShell();
      const flush = vi.spyOn(f.persistence, "flush");
      const link = screen.getByRole("link", {
        name: f.preferences.messages.resumeTemplates,
      });
      await act(async () => {
        if (event === "focus") fireEvent.focus(link);
        else fireEvent.pointerEnter(link);
      });
      expect(preloadWorkspaceRoute).toHaveBeenCalledExactlyOnceWith(
        "templates",
      );
      expect(flush).not.toHaveBeenCalled();
      expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
      expect(f.router.state.location.pathname).toBe("/resume");
    },
  );

  it("waits for queued preference writes before fetching a clicked destination", async () => {
    const f = fixture("/resume");
    const saved = deferred<{ theme: "dark" }>();
    const save = vi.fn(() => saved.promise);
    f.preferences.persistence = createWorkspacePreferencesPersistence(
      f.persistence.getSnapshot(),
      { save, onChange: vi.fn(), onError: vi.fn() },
    );
    render(
      <WorkspaceShell activeView="resume" onLogout={vi.fn()}>
        Current gallery
      </WorkspaceShell>,
      { wrapper: f.wrapper },
    );
    const data = templates("dark");
    vi.mocked(fetchWorkspaceRouteData).mockResolvedValue(data);
    f.preferences.persistence.change({ theme: "dark" });
    await act(async () =>
      fireEvent.click(
        screen.getByRole("link", {
          name: f.preferences.messages.resumeTemplates,
        }),
      ),
    );
    expect(save).toHaveBeenCalledExactlyOnceWith({ theme: "dark" }, "en");
    expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    expect(f.router.state.location.pathname).toBe("/resume");
    await act(async () => {
      saved.resolve({ theme: "dark" });
    });
    expect(fetchWorkspaceRouteData).toHaveBeenCalledExactlyOnceWith(
      "template-gallery",
      { notifyOnError: false, signal: expect.any(AbortSignal) },
    );
    expect(f.router.state.location.pathname).toBe("/templates");
    expect(
      getWorkspaceLateralRouteHandoff(f.router.state.location.state)?.data,
    ).toBe(data.data);
  });

  it("prepares and commits only the latest clicked destination", async () => {
    const f = setupShell();
    const oldRead = deferred<WorkspaceRouteDataResult>();
    const newRead = deferred<WorkspaceRouteDataResult>();
    vi.mocked(fetchWorkspaceRouteData)
      .mockReturnValueOnce(oldRead.promise)
      .mockReturnValueOnce(newRead.promise);
    const templatesLink = screen.getByRole("link", {
      name: f.preferences.messages.resumeTemplates,
    });
    const settingsLink = screen.getByRole("link", {
      name: f.preferences.messages.settings,
    });
    await act(async () => fireEvent.click(templatesLink));
    const signal = vi.mocked(fetchWorkspaceRouteData).mock.calls[0][1]!.signal!;
    expect(templatesLink.getAttribute("aria-busy")).toBe("true");
    await act(async () => fireEvent.click(settingsLink));
    expect(signal.aborted).toBe(true);
    expect(templatesLink.hasAttribute("aria-busy")).toBe(false);
    expect(settingsLink.getAttribute("aria-busy")).toBe("true");
    await act(async () => {
      oldRead.resolve(templates());
    });
    expect(f.router.state.location.pathname).toBe("/resume");
    const data = {
      modelConfigs: [],
      agentSettings: f.preferences.agentSettings!,
    };
    await act(async () => {
      newRead.resolve({ kind: "settings", data });
    });
    expect(f.router.state.location.pathname).toBe("/settings");
    expect(
      getWorkspaceLateralRouteHandoff(f.router.state.location.state)?.data,
    ).toBe(data);
    expect(settingsLink.hasAttribute("aria-busy")).toBe(false);
  });

  it.each(["active entry", "logout"] as const)(
    "%s supersedes another owner's pending intent",
    async (action) => {
      const f = setupShell();
      const other = fixture("/resume");
      const { result } = renderHook(useWorkspaceNavigationTransaction, {
        wrapper: other.wrapper,
      });
      const intent = result.current.beginNavigation();
      await act(async () =>
        fireEvent.click(
          action === "active entry"
            ? screen.getByRole("link", {
                name: f.preferences.messages.myResume,
              })
            : screen.getByRole("button", {
                name: f.preferences.messages.logout,
              }),
        ),
      );
      expect(intent.signal.aborted).toBe(true);
      expect(intent.isCurrent()).toBe(false);
      expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
      expect(f.onLogout).toHaveBeenCalledTimes(action === "logout" ? 1 : 0);
      expect(f.router.state.location.pathname).toBe("/resume");
    },
  );

  it("cleans up the handoff and pending indicator when history rejects a sidebar commit", async () => {
    const f = setupShell();
    vi.mocked(fetchWorkspaceRouteData).mockResolvedValue(templates());
    const error = new DOMException(
      "History cannot clone this navigation",
      "DataCloneError",
    );
    const push = vi
      .spyOn(window.history, "pushState")
      .mockImplementation(() => {
        throw error;
      });
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const link = screen.getByRole("link", {
      name: f.preferences.messages.resumeTemplates,
    });
    const gallery = screen.getByText("Current gallery");
    await act(async () => fireEvent.click(link));
    const state = push.mock.calls[0][0] as { usr: { token: string } };
    expect(readWorkspaceHandoffToken(state.usr.token)).toBeUndefined();
    expect(showWorkspaceNavigationError).toHaveBeenCalledExactlyOnceWith(
      f.preferences.messages.loadError,
    );
    expect(f.router.state.location.pathname).toBe("/resume");
    expect(screen.getByText("Current gallery")).toBe(gallery);
    expect(link.hasAttribute("aria-busy")).toBe(false);
  });

  it("keeps the mounted gallery and clears its pending indicator after a preparation error", async () => {
    const f = setupShell();
    const error = new Error("route offline");
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.mocked(fetchWorkspaceRouteData).mockRejectedValueOnce(error);
    const gallery = screen.getByText("Current gallery");
    const link = screen.getByRole("link", {
      name: f.preferences.messages.resumeTemplates,
    });
    await act(async () => fireEvent.click(link));
    expect(f.router.state.location.pathname).toBe("/resume");
    expect(screen.getByText("Current gallery")).toBe(gallery);
    expect(link.hasAttribute("aria-busy")).toBe(false);
    expect(showWorkspaceNavigationError).toHaveBeenCalledExactlyOnceWith(
      f.preferences.messages.loadError,
    );
  });
});
