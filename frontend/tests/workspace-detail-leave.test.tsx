import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useResumeDetailLeave } from "@/components/workspace/use-resume-detail-leave";
import { useTemplateDetailLeave } from "@/components/workspace/use-template-detail-leave";
import { notifyApiError } from "@/lib/api-error-notifier";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";

vi.mock("@/lib/api-error-notifier", () => ({ notifyApiError: vi.fn() }));
vi.mock("sonner", () => ({ toast: { warning: vi.fn() } }));

const disposers: (() => void)[] = [];
const leaveHooks = [
  { kind: "resume", useLeave: useResumeDetailLeave },
  { kind: "template", useLeave: useTemplateDetailLeave },
] as const;
function setup(useLeave: (typeof leaveHooks)[number]["useLeave"]) {
  const f = createWorkspaceFixture({ path: "/resume/detail" });
  disposers.push(() => f.router.dispose());
  const state = { dirty: false, promote: false };
  const options = {
    discard: vi.fn(async () => {
      state.dirty = false;
    }),
    save: vi.fn(async () => {
      state.dirty = false;
    }),
    hasUnsavedChanges: () => state.dirty,
    requiresCheckpointPromotion: () => state.promote,
    promoteCheckpoint: vi.fn(async () => {
      state.promote = false;
    }),
    markCheckpointPromotionSkipped: vi.fn(() => {
      state.promote = false;
    }),
    messages: f.preferences.messages,
  };
  return {
    ...f,
    ...renderHook(() => useLeave(options), { wrapper: f.wrapper }),
    options,
    state,
  };
}
afterEach(() => {
  cleanup();
  disposers.splice(0).forEach((dispose) => dispose());
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe.each(leaveHooks)("$kind detail leave protection", ({ useLeave }) => {
  it("runs a clean leave immediately and ignores save/discard without a pending action", async () => {
    const f = setup(useLeave);
    const run = vi.fn();
    act(() => f.result.current.requestLeave(run));
    await act(async () => {
      await f.result.current.saveAndLeave();
      await f.result.current.discardAndLeave();
    });
    expect(run).toHaveBeenCalledTimes(1);
    expect(f.result.current.isOpen).toBe(false);
    expect(f.options.save).not.toHaveBeenCalled();
    expect(f.options.discard).not.toHaveBeenCalled();
    expect(f.options.promoteCheckpoint).not.toHaveBeenCalled();
  });

  it("keeps a dirty draft in place and cancels the latest requested leave", () => {
    const f = setup(useLeave);
    f.state.dirty = true;
    const oldRun = vi.fn(),
      oldCancel = vi.fn(),
      run = vi.fn(),
      cancel = vi.fn();
    act(() => f.result.current.requestLeave(oldRun, oldCancel));
    expect(f.result.current.isOpen).toBe(true);
    act(() => f.result.current.requestLeave(run, cancel));
    act(() => f.result.current.cancelLeave());
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(oldCancel).not.toHaveBeenCalled();
    expect(oldRun).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
    expect(f.result.current.isOpen).toBe(false);
    expect(f.state.dirty).toBe(true);
    expect(f.options.save).not.toHaveBeenCalled();
    expect(f.options.discard).not.toHaveBeenCalled();
  });

  it.each(["save", "discard"] as const)(
    "awaits %s, prevents another resolution, then runs the leave once",
    async (operation) => {
      const f = setup(useLeave);
      f.state.dirty = true;
      const settled = Promise.withResolvers<void>();
      f.options[operation].mockImplementationOnce(() => settled.promise);
      const run = vi.fn();
      act(() => f.result.current.requestLeave(run));
      let pending: Promise<void> | undefined;
      act(() => {
        pending =
          operation === "save"
            ? f.result.current.saveAndLeave()
            : f.result.current.discardAndLeave();
      });
      expect(f.result.current.isResolving).toBe(true);
      expect(f.result.current.isOpen).toBe(true);
      expect(run).not.toHaveBeenCalled();
      await act(async () => {
        await f.result.current.saveAndLeave();
        await f.result.current.discardAndLeave();
      });
      expect(f.options[operation]).toHaveBeenCalledTimes(1);
      expect(
        f.options[operation === "save" ? "discard" : "save"],
      ).not.toHaveBeenCalled();
      await act(async () => {
        settled.resolve();
        await pending;
      });
      expect(run).toHaveBeenCalledTimes(1);
      expect(f.result.current.isOpen).toBe(false);
      expect(f.result.current.isResolving).toBe(false);
    },
  );

  it.each(["save", "discard"] as const)(
    "keeps the dialog and draft after %s fails, allowing a successful retry",
    async (operation) => {
      const f = setup(useLeave);
      f.state.dirty = true;
      const error = new Error(`${operation} unavailable`);
      const log = vi
        .spyOn(console, "error")
        .mockImplementation(() => undefined);
      f.options[operation].mockRejectedValueOnce(error);
      const run = vi.fn();
      act(() => f.result.current.requestLeave(run));
      await act(async () => {
        if (operation === "save") await f.result.current.saveAndLeave();
        else await f.result.current.discardAndLeave();
      });
      expect(run).not.toHaveBeenCalled();
      expect(f.state.dirty).toBe(true);
      expect(f.result.current.isOpen).toBe(true);
      expect(f.result.current.isResolving).toBe(false);
      expect(notifyApiError).toHaveBeenCalledExactlyOnceWith(
        error,
        f.options.messages.loadError,
      );
      expect(log).toHaveBeenCalledWith(expect.any(String), error);
      await act(async () => {
        if (operation === "save") await f.result.current.saveAndLeave();
        else await f.result.current.discardAndLeave();
      });
      expect(run).toHaveBeenCalledTimes(1);
      expect(f.options[operation]).toHaveBeenCalledTimes(2);
      expect(f.state.dirty).toBe(false);
      expect(f.result.current.isOpen).toBe(false);
    },
  );

  it("blocks browser unload only for a current dirty draft and removes its listener on unmount", () => {
    const f = setup(useLeave);
    const unload = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(unload()).toBe(false);
    f.state.promote = true;
    expect(unload()).toBe(false);
    f.state.dirty = true;
    expect(unload()).toBe(true);
    f.state.dirty = false;
    expect(unload()).toBe(false);
    f.state.dirty = true;
    f.unmount();
    expect(unload()).toBe(false);
  });

  it.each(["save", "discard"] as const)(
    "blocks POP, resets a canceled attempt, then proceeds after %s",
    async (operation) => {
      const f = setup(useLeave);
      await act(() => f.router.navigate("/resume/detail?section=2"));
      f.state.dirty = true;
      await act(() => f.router.navigate(-1));
      expect(f.router.state.location.search).toBe("?section=2");
      expect(f.result.current.isOpen).toBe(true);
      f.rerender();
      expect(f.result.current.isOpen).toBe(true);
      act(() => f.result.current.cancelLeave());
      expect(f.router.state.location.search).toBe("?section=2");
      expect(f.result.current.isOpen).toBe(false);
      await act(() => f.router.navigate(-1));
      expect(f.result.current.isOpen).toBe(true);
      await act(async () => {
        if (operation === "save") await f.result.current.saveAndLeave();
        else await f.result.current.discardAndLeave();
      });
      expect(f.options[operation]).toHaveBeenCalledTimes(1);
      expect(f.router.state.location.search).toBe("");
      expect(f.result.current.isOpen).toBe(false);
    },
  );
});

describe("resume autosave checkpoint promotion", () => {
  it("waits for a shared promotion for every leave callback and can promote again later", async () => {
    const f = setup(useResumeDetailLeave);
    f.state.promote = true;
    const promotion = Promise.withResolvers<void>();
    f.options.promoteCheckpoint.mockImplementationOnce(() => promotion.promise);
    const first = vi.fn(),
      second = vi.fn();
    act(() => {
      f.result.current.requestLeave(first);
      f.result.current.requestLeave(second);
    });
    expect(f.options.promoteCheckpoint).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();
    expect(f.result.current.isOpen).toBe(false);
    await act(async () => {
      promotion.resolve();
    });
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
    expect(first.mock.invocationCallOrder[0]).toBeLessThan(
      second.mock.invocationCallOrder[0],
    );
    await act(async () => f.result.current.requestLeave(first));
    expect(f.options.promoteCheckpoint).toHaveBeenCalledTimes(2);
    expect(first).toHaveBeenCalledTimes(2);
  });

  it("re-checks edits made during promotion and asks to resolve them before leaving", async () => {
    const f = setup(useResumeDetailLeave);
    f.state.promote = true;
    const promotion = Promise.withResolvers<void>();
    f.options.promoteCheckpoint.mockReturnValueOnce(promotion.promise);
    const run = vi.fn(),
      cancel = vi.fn();
    act(() => f.result.current.requestLeave(run, cancel));
    f.state.dirty = true;
    await act(async () => {
      promotion.resolve();
    });
    expect(run).not.toHaveBeenCalled();
    expect(f.result.current.isOpen).toBe(true);
    expect(f.options.save).not.toHaveBeenCalled();
    act(() => f.result.current.cancelLeave());
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(f.state.dirty).toBe(true);
  });

  it("warns once for a shared history-only failure and releases every waiting leave", async () => {
    const f = setup(useResumeDetailLeave);
    f.state.promote = true;
    const promotion = Promise.withResolvers<void>();
    const error = new Error("history unavailable");
    f.options.promoteCheckpoint.mockReturnValueOnce(promotion.promise);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const first = vi.fn(),
      second = vi.fn();
    act(() => {
      f.result.current.requestLeave(first);
      f.result.current.requestLeave(second);
    });
    await act(async () => {
      promotion.reject(error);
    });
    expect(f.options.markCheckpointPromotionSkipped).toHaveBeenCalledTimes(1);
    expect(toast.warning).toHaveBeenCalledExactlyOnceWith(
      f.options.messages.checkpointPromotionFailed,
      { closeButton: true, id: "checkpoint-promotion-failed" },
    );
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
    expect(f.result.current.isOpen).toBe(false);
    expect(notifyApiError).not.toHaveBeenCalled();
  });

  it("holds browser history navigation until checkpoint promotion settles without a dirty dialog", async () => {
    const f = setup(useResumeDetailLeave);
    await act(() => f.router.navigate("/resume/detail?section=2"));
    f.state.promote = true;
    const promotion = Promise.withResolvers<void>();
    f.options.promoteCheckpoint.mockReturnValueOnce(promotion.promise);
    await act(() => f.router.navigate(-1));
    expect(f.options.promoteCheckpoint).toHaveBeenCalledTimes(1);
    expect(f.router.state.location.search).toBe("?section=2");
    expect(f.result.current.isOpen).toBe(false);
    f.rerender();
    expect(f.options.promoteCheckpoint).toHaveBeenCalledTimes(1);
    await act(async () => {
      f.state.promote = false;
      promotion.resolve();
    });
    expect(f.router.state.location.search).toBe("");
    expect(f.result.current.isOpen).toBe(false);
  });
});
