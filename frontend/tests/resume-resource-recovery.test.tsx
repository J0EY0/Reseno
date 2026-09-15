import { act, cleanup, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { BrowserRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useResumeDetailSave } from "@/components/workspace/use-resume-detail-save";
import { useResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import { useResumeResourceRecovery } from "@/components/workspace/use-resume-resource-recovery";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import { defaultMessages } from "@/i18n";
import { fetchResumeVersionsApi, saveResumeApi } from "@/lib/workspace-api";
import type { ResumeDetailResponse } from "@/types/api";

import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";

vi.mock("@/hooks/use-auth-session-token", () => ({
  useAuthSessionToken: () => "session-token",
}));
vi.mock("sonner", () => ({ toast: { dismiss: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/workspace-api", () => ({
  saveResumeApi: vi.fn(),
  fetchResumeVersionsApi: vi.fn(),
  fetchResumeVersionApi: vi.fn(),
}));

const reload = vi.fn();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  window.history.replaceState({ key: "initial" }, "", "/resume/a");
  vi.stubGlobal(
    "window",
    new Proxy(window, {
      get(target, key) {
        return key === "location"
          ? new Proxy(
              {},
              {
                get(_location, property) {
                  return property === "reload"
                    ? reload
                    : Reflect.get(target.location, property, target.location);
                },
              },
            )
          : Reflect.get(target, key, target);
      },
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function renderRecovery() {
  const initial = createResumeDetailItem();
  const held = Promise.withResolvers<ResumeDetailResponse>();
  const response = (payload: Parameters<typeof saveResumeApi>[1]) => ({
    resume: { ...initial, ...payload },
    savedAt: initial.updatedAt,
    versionId: "saved-version",
  });
  vi.mocked(saveResumeApi)
    .mockReset()
    .mockImplementationOnce(() => held.promise)
    .mockImplementation(async (_id, payload) => response(payload));
  vi.mocked(fetchResumeVersionsApi).mockResolvedValue({ versions: [] });
  const hook = renderHook(
    () => {
      const session = useResumeDetailSession({ initialResume: initial });
      const save = useResumeDetailSave({
        getFingerprint: session.getFingerprint,
        getSnapshot: session.getSnapshot,
        initialResume: initial,
        isLoading: false,
        liveFingerprint: session.fingerprint,
        liveResume: session.document,
        messages: defaultMessages,
        onAdoptSavedResume: session.adoptSavedResume,
        onHydrateResume: session.hydrate,
        resumeId: initial.id,
      });
      const { beginNavigation } = useWorkspaceNavigationTransaction();
      return {
        session,
        save,
        beginNavigation,
        navigate: useNavigate(),
        recover: useResumeResourceRecovery({ save, beginNavigation }),
      };
    },
    {
      wrapper: ({ children }: PropsWithChildren) => (
        <BrowserRouter>{children}</BrowserRouter>
      ),
    },
  );
  const edit = (phone: string) =>
    hook.result.current.session.updateContent((resume) => ({
      ...resume,
      basic: { ...resume.basic, phone },
    }));
  act(() => edit("first edit"));
  return {
    ...hook,
    edit,
    held,
    finishFirstSave: () =>
      held.resolve(response(vi.mocked(saveResumeApi).mock.calls[0][1])),
  };
}

describe("resume resource recovery", () => {
  it("waits for persistence and shares simultaneous recovery clicks", async () => {
    const f = renderRecovery();
    let recovery!: Promise<void>;
    act(() => {
      recovery = f.result.current.recover();
      expect(f.result.current.recover()).toBe(recovery);
    });
    expect(saveResumeApi).toHaveBeenCalledExactlyOnceWith(
      "resume-a",
      expect.objectContaining({
        resume: expect.objectContaining({
          basic: expect.objectContaining({ phone: "first edit" }),
        }),
      }),
      "checkpoint",
      { notifyOnError: false },
    );
    expect(reload).not.toHaveBeenCalled();
    await act(async () => {
      f.finishFirstSave();
      await recovery;
    });
    expect(reload).toHaveBeenCalledOnce();
    expect(f.result.current.save.hasUnsavedChanges()).toBe(false);
  });

  it("persists typing committed in the same batch as the first save receipt", async () => {
    const f = renderRecovery();
    let recovery!: Promise<void>;
    act(() => {
      recovery = f.result.current.recover();
    });
    await act(async () => {
      f.edit("latest edit");
      f.finishFirstSave();
      await recovery;
    });
    expect(
      vi.mocked(saveResumeApi).mock.calls.map(([, p]) => p.resume.basic.phone),
    ).toEqual(["first edit", "latest edit"]);
    expect(f.result.current.session.resume.basic.phone).toBe("latest edit");
    expect(f.result.current.save.hasUnsavedChanges()).toBe(false);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("waits for an existing autosave before checkpointing newer edits", async () => {
    const f = renderRecovery();
    let autosave!: Promise<ResumeDetailResponse>;
    let recovery!: Promise<void>;
    act(() => {
      autosave = f.result.current.save.save("autosave");
    });
    act(() => f.edit("after autosave"));
    act(() => {
      recovery = f.result.current.recover();
    });
    expect(saveResumeApi).toHaveBeenCalledOnce();
    await act(async () => {
      f.finishFirstSave();
      await Promise.all([autosave, recovery]);
    });
    expect(
      vi
        .mocked(saveResumeApi)
        .mock.calls.map(([, p, mode]) => [p.resume.basic.phone, mode]),
    ).toEqual([
      ["first edit", "autosave"],
      ["after autosave", "checkpoint"],
    ]);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("rejects a failed save, preserves editing and permits a later recovery", async () => {
    const f = renderRecovery();
    const failure = new Error("Save is unavailable");
    let recovery!: Promise<void>;
    act(() => {
      recovery = f.result.current.recover();
    });
    const rejection = expect(recovery).rejects.toBe(failure);
    await act(async () => {
      f.held.reject(failure);
      await rejection;
    });
    expect(reload).not.toHaveBeenCalled();
    expect(f.result.current.session.resume.basic.phone).toBe("first edit");
    expect(f.result.current.save.hasUnsavedChanges()).toBe(true);
    act(() => f.edit("retry edit"));
    await act(async () => f.result.current.recover());
    expect(saveResumeApi).toHaveBeenCalledTimes(2);
    expect(vi.mocked(saveResumeApi).mock.lastCall?.[1].resume.basic.phone).toBe(
      "retry edit",
    );
    expect(reload).toHaveBeenCalledOnce();
  });

  it.each(["abort", "newer navigation", "route change", "unmount"] as const)(
    "does not reload after %s during a save",
    async (cancellation) => {
      const f = renderRecovery();
      const controller = new AbortController();
      let recovery!: Promise<void>;
      act(() => {
        recovery = f.result.current.recover(controller.signal);
      });
      const rejection = expect(recovery).rejects.toMatchObject({
        name: "AbortError",
      });
      act(() => {
        if (cancellation === "abort") controller.abort();
        else if (cancellation === "newer navigation")
          f.result.current.beginNavigation();
        else if (cancellation === "route change")
          f.result.current.navigate("/resume/b");
        else f.unmount();
      });
      await act(async () => {
        f.finishFirstSave();
        await rejection;
      });
      expect(saveResumeApi).toHaveBeenCalledOnce();
      expect(reload).not.toHaveBeenCalled();
    },
  );

  it.each(["already aborted", "already unmounted"] as const)(
    "does not start persistence when %s",
    async (cancellation) => {
      const f = renderRecovery();
      const recover = f.result.current.recover;
      const controller = new AbortController();
      if (cancellation === "already aborted") controller.abort();
      else f.unmount();
      await expect(recover(controller.signal)).rejects.toMatchObject({
        name: "AbortError",
      });
      expect(saveResumeApi).not.toHaveBeenCalled();
      expect(reload).not.toHaveBeenCalled();
    },
  );
});
