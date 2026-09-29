import { act, cleanup, renderHook } from "@testing-library/react";
import { useCallback, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { useAuthSessionToken } from "@/hooks/use-auth-session-token";
import { resolveAgentDraftDecision } from "@/lib/agent-session-run-client";

import { useResumeDetailSave } from "@/components/workspace/use-resume-detail-save";
import { useResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import { useTemplateDetailSave } from "@/components/workspace/use-template-detail-save";
import { defaultMessages } from "@/i18n";
import * as i18n from "@/i18n";
import {
  fetchResumeVersionApi,
  fetchResumeVersionsApi,
  saveResumeApi,
  saveTemplateApi,
} from "@/lib/workspace-api";
import {
  countResumeChanges,
  countTemplateChanges,
  createResumeFingerprint,
  createTemplateFingerprint,
} from "@/lib/workspace-change-tracking";
import type { ResumeDetailResponse } from "@/types/api";
import type { ResumeWorkspaceItem } from "@/types/resume";

import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

vi.mock("@/hooks/use-auth-session-token", () => ({
  useAuthSessionToken: vi.fn(() => "session-token"),
}));
vi.mock("sonner", () => ({ toast: { dismiss: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api-error-notifier", () => ({ notifyApiError: vi.fn() }));
vi.mock("@/lib/agent-session-run-client", () => ({
  resolveAgentDraftDecision: vi.fn(() => {
    throw new Error("Unexpected Agent decision");
  }),
}));
vi.mock("@/lib/workspace-api", () => ({
  saveResumeApi: vi.fn(),
  fetchResumeVersionsApi: vi.fn(),
  fetchResumeVersionApi: vi.fn(),
  saveTemplateApi: vi.fn(),
  discardTemplateChangesApi: vi.fn(() => {
    throw new Error("Unexpected discard request");
  }),
}));
vi.mock("@/lib/workspace-change-tracking", { spy: true });
const tracking = await vi.importActual<
  typeof import("@/lib/workspace-change-tracking")
>("@/lib/workspace-change-tracking");

function detail(
  resume: ResumeWorkspaceItem,
  versionId = "version-a",
): ResumeDetailResponse {
  return { resume, versionId, savedAt: resume.updatedAt };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function renderSave({
  save,
  version,
}: {
  save?: (
    ...args: Parameters<typeof saveResumeApi>
  ) => ReturnType<typeof saveResumeApi>;
  version?: typeof fetchResumeVersionApi;
} = {}) {
  const initial = createResumeDetailItem();
  const checkpoint = { savedAt: initial.updatedAt, versionId: "version-a" };
  vi.mocked(saveResumeApi).mockImplementation(
    save ??
      (async (_id, payload) => {
        const count = vi.mocked(saveResumeApi).mock.calls.length;
        return detail(
          { ...initial, ...payload, updatedAt: `saved-${count}` },
          `version-${count + 1}`,
        );
      }),
  );
  vi.mocked(fetchResumeVersionsApi).mockResolvedValue({
    versions: [checkpoint],
  });
  vi.mocked(fetchResumeVersionApi).mockImplementation(
    version ??
      (() => {
        throw new Error("Unexpected historical read");
      }),
  );
  const hydrate = vi.fn();
  const initialProps: { isLoading: boolean; autosavePaused?: boolean } = {
    isLoading: false,
  };
  const hook = renderHook(
    (props: typeof initialProps) => {
      const isLoading = props?.isLoading ?? false;
      const session = useResumeDetailSession({ initialResume: initial });
      const hydrateSession = session.hydrate;
      const onHydrateResume = useCallback(
        (resume: ResumeWorkspaceItem) => {
          hydrate(resume);
          hydrateSession(resume);
        },
        [hydrateSession],
      );
      const persistence = useResumeDetailSave({
        autosavePaused: props?.autosavePaused ?? false,
        getFingerprint: session.getFingerprint,
        getSnapshot: session.getSnapshot,
        initialCheckpoint: checkpoint,
        initialResume: initial,
        isLoading,
        liveFingerprint: session.fingerprint,
        liveResume: session.document,
        messages: defaultMessages,
        onAdoptSavedResume: session.adoptSavedResume,
        onHydrateResume,
        resumeId: initial.id,
      });
      return { session, persistence };
    },
    { initialProps },
  );
  return {
    ...hook,
    hydrate,
    edit: (resume: ResumeWorkspaceItem) =>
      act(() => hook.result.current.session.hydrate(resume)),
  };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.mocked(useAuthSessionToken).mockReturnValue("session-token");
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("resume detail save", () => {
  it.each([
    [true, true],
    [false, true],
    [true, false],
  ])(
    "serializes Agent decisions after saves and adopts only a confirmed requested commit (%s, %s)",
    async (committed, resolvedAsRequested) => {
      const gate = deferred<ResumeDetailResponse>();
      const fixture = renderSave({ save: () => gate.promise });
      const submitted = {
        ...createResumeDetailItem(),
        title: "Submitted title",
      };
      fixture.edit(submitted);
      let saving!: Promise<ResumeDetailResponse>;
      act(() => {
        saving = fixture.result.current.persistence.save();
      });
      fixture.edit({ ...submitted, title: "Newer local title" });
      const official = detail(
        { ...submitted, title: "Agent title" },
        "agent-version",
      );
      vi.mocked(resolveAgentDraftDecision).mockResolvedValue({
        committed,
        resolvedAsRequested,
        draft: null,
        resume: official,
        session: {
          resumeId: submitted.id,
          revision: "revision",
          messages: [],
          executions: [],
        },
      });
      let decision!: ReturnType<typeof resolveAgentDraftDecision>;
      act(() => {
        decision = fixture.result.current.persistence.resolveAgentDraftReview(
          "message",
          submitted.resume,
          ["review-item"],
          "applied",
        );
      });
      expect(resolveAgentDraftDecision).not.toHaveBeenCalled();
      await act(async () => {
        gate.resolve(detail(submitted, "saved-version"));
        await saving;
        await decision;
      });
      expect(resolveAgentDraftDecision).toHaveBeenCalledExactlyOnceWith(
        submitted.id,
        "message",
        {
          conflictResolution: undefined,
          currentResume: submitted.resume,
          currentVersionId: "saved-version",
          rebaseOnLatest: false,
          reviewItemIds: ["review-item"],
          status: "applied",
        },
      );
      expect((await decision).resume).toEqual(
        committed && resolvedAsRequested ? official : null,
      );
      expect(fixture.result.current.session.document?.title).toBe(
        "Newer local title",
      );
      expect(fixture.result.current.persistence.activeVersionId).toBe(
        committed && resolvedAsRequested ? "agent-version" : "saved-version",
      );
    },
  );

  it("debounces edits, saves a continuous typing burst by 30 seconds and restarts after a clean checkpoint", async () => {
    const fixture = renderSave();
    for (let index = 0; index < 8; index += 1) {
      if (index > 0) await act(() => vi.advanceTimersByTimeAsync(4000));
      fixture.edit({ ...createResumeDetailItem(), title: `Draft ${index}` });
      expect(saveResumeApi).not.toHaveBeenCalled();
    }
    await act(() => vi.advanceTimersByTimeAsync(1999));
    expect(saveResumeApi).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(saveResumeApi).toHaveBeenCalledOnce();
    expect(vi.mocked(saveResumeApi).mock.calls[0][1].title).toBe("Draft 7");
    expect(vi.mocked(saveResumeApi).mock.calls[0][2]).toBe("autosave");
    await act(() => fixture.result.current.persistence.save("checkpoint"));
    const count = vi.mocked(saveResumeApi).mock.calls.length;
    fixture.edit({ ...createResumeDetailItem(), title: "New burst" });
    await act(() => vi.advanceTimersByTimeAsync(4999));
    expect(saveResumeApi).toHaveBeenCalledTimes(count);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(saveResumeApi).toHaveBeenCalledTimes(count + 1);
    expect(toast.dismiss).toHaveBeenCalledWith("autosave-failed");
  });

  it.each(["loading", "signed-out"])(
    "pauses pending autosave while %s and resumes only when ready",
    async (condition) => {
      const fixture = renderSave();
      fixture.edit({ ...createResumeDetailItem(), title: "Pending edit" });
      await act(() => vi.advanceTimersByTimeAsync(4000));
      if (condition === "signed-out")
        vi.mocked(useAuthSessionToken).mockReturnValue(null);
      fixture.rerender({ isLoading: condition === "loading" });
      await act(() => vi.advanceTimersByTimeAsync(10000));
      expect(saveResumeApi).not.toHaveBeenCalled();
      vi.mocked(useAuthSessionToken).mockReturnValue("session-token");
      fixture.rerender({ isLoading: false });
      await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(saveResumeApi).toHaveBeenCalledOnce();
      fixture.edit({ ...createResumeDetailItem(), title: "Unmounted edit" });
      fixture.unmount();
      await act(() => vi.advanceTimersByTimeAsync(30000));
      expect(saveResumeApi).toHaveBeenCalledOnce();
    },
  );

  it("cancels queued autosave when paused and saves newer edits after resuming", async () => {
    const fixture = renderSave();
    const gate = deferred<ResumeDetailResponse>();
    vi.mocked(saveResumeApi).mockImplementationOnce(() => gate.promise);
    const submitted = { ...createResumeDetailItem(), title: "Submitted title" };
    fixture.edit(submitted);
    let saving!: Promise<ResumeDetailResponse>;
    act(() => {
      saving = fixture.result.current.persistence.save();
    });
    fixture.edit({ ...submitted, title: "Newer title" });
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(saveResumeApi).toHaveBeenCalledOnce();
    fixture.rerender({ isLoading: false, autosavePaused: true });
    await act(async () => {
      gate.resolve(detail({ ...submitted, updatedAt: "saved" }, "version-b"));
      await saving;
    });
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(saveResumeApi).toHaveBeenCalledOnce();
    expect(fixture.result.current.persistence.hasUnsavedChanges()).toBe(true);
    fixture.rerender({ isLoading: false, autosavePaused: false });
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(saveResumeApi).toHaveBeenCalledTimes(2);
    expect(vi.mocked(saveResumeApi).mock.calls[1][1].title).toBe("Newer title");
    expect(vi.mocked(saveResumeApi).mock.calls[1][2]).toBe("autosave");
    expect(fixture.result.current.persistence.hasUnsavedChanges()).toBe(false);
  });

  it("retries failed autosave at bounded delays and clears the final warning after manual checkpoint", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const fixture = renderSave();
    const saved = vi.mocked(saveResumeApi).getMockImplementation()!;
    vi.mocked(saveResumeApi).mockRejectedValue(new Error("Offline"));
    fixture.edit({ ...createResumeDetailItem(), title: "Pending edit" });
    for (const [delay, count] of [
      [5000, 1],
      [2000, 2],
      [5000, 3],
    ]) {
      await act(() => vi.advanceTimersByTimeAsync(delay));
      expect(saveResumeApi).toHaveBeenCalledTimes(count);
    }
    expect(toast.error).toHaveBeenCalledExactlyOnceWith(
      defaultMessages.loadError,
      { closeButton: true, id: "autosave-failed" },
    );
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(saveResumeApi).toHaveBeenCalledTimes(3);
    vi.mocked(saveResumeApi).mockImplementation(saved);
    await act(() => fixture.result.current.persistence.save("checkpoint"));
    expect(fixture.result.current.persistence.hasUnsavedChanges()).toBe(false);
    expect(toast.dismiss).toHaveBeenCalledWith("autosave-failed");
    fixture.edit({ ...createResumeDetailItem(), title: "New edit" });
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(saveResumeApi).toHaveBeenCalledTimes(5);
  });

  it("returns the persisted snapshot while keeping newer typing unsaved", async () => {
    const gate = deferred<ResumeDetailResponse>();
    const { result, edit } = renderSave({ save: () => gate.promise });
    const submitted = { ...createResumeDetailItem(), title: "Submitted title" };
    edit(submitted);
    let saving!: Promise<ResumeDetailResponse>;
    act(() => {
      saving = result.current.persistence.save();
    });
    edit({ ...submitted, title: "Typed while saving" });
    let saved!: ResumeDetailResponse;
    await act(async () => {
      gate.resolve(detail({ ...submitted, updatedAt: "saved" }, "version-b"));
      saved = await saving;
    });
    expect(vi.mocked(saveResumeApi).mock.calls[0][1].title).toBe(
      "Submitted title",
    );
    expect(saved.resume.title).toBe("Submitted title");
    expect(result.current.persistence.hasUnsavedChanges()).toBe(true);
    expect(result.current.persistence.changeCount).toBe(1);
    expect(result.current.persistence.activeVersionId).toBe("version-b");
  });

  it("promotes a clean autosave once and reuses its checkpoint receipt", async () => {
    const { result, edit } = renderSave();
    edit({ ...createResumeDetailItem(), title: "Autosaved title" });
    await act(async () => {
      await result.current.persistence.save("autosave");
    });
    expect(result.current.persistence.hasUnsavedChanges()).toBe(false);
    expect(result.current.persistence.changeCount).toBe(0);
    expect(result.current.persistence.requiresCheckpointPromotion()).toBe(true);
    let checkpointReceipt!: ResumeDetailResponse;
    await act(async () => {
      checkpointReceipt = await result.current.persistence.save("checkpoint");
    });
    expect(vi.mocked(saveResumeApi).mock.calls.map((call) => call[2])).toEqual([
      "autosave",
      "checkpoint",
    ]);
    expect(result.current.persistence.requiresCheckpointPromotion()).toBe(
      false,
    );
    await act(async () => {
      expect(await result.current.persistence.save()).toEqual(
        checkpointReceipt,
      );
    });
    expect(saveResumeApi).toHaveBeenCalledTimes(2);
  });

  it("previews history without replacing or autosaving the current document", async () => {
    const selected = {
      ...createResumeDetailItem(),
      title: "Historical title",
      updatedAt: "historical-time",
    };
    const { result, edit } = renderSave({
      version: async () => detail(selected, "version-old"),
    });
    const current = {
      ...createResumeDetailItem(),
      title: "Loaded current title",
      updatedAt: "current-time",
    };
    edit(current);
    act(() =>
      result.current.persistence.hydratePersistedResume(
        detail(current, "version-current"),
        [
          { versionId: "version-current", savedAt: current.updatedAt },
          { versionId: "version-old", savedAt: selected.updatedAt },
        ],
      ),
    );
    expect(result.current.persistence.hasUnsavedChanges()).toBe(false);
    expect(result.current.persistence.changeCount).toBe(0);
    await act(async () => {
      await result.current.persistence.selectVersion("version-old");
    });
    expect(result.current.session.document?.title).toBe("Loaded current title");
    expect(result.current.persistence.historyVersion?.resume).toEqual(selected);
    expect(result.current.persistence.isViewingHistory).toBe(true);
    expect(result.current.persistence.activeVersionId).toBe("version-current");
    expect(result.current.persistence.lastSavedAt).toBe("current-time");
    expect(result.current.persistence.hasUnsavedChanges()).toBe(false);
    expect(result.current.persistence.changeCount).toBe(0);
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    await act(() => result.current.persistence.save());
    expect(saveResumeApi).not.toHaveBeenCalled();
    act(() => result.current.persistence.returnToLatest());
    expect(result.current.persistence.isViewingHistory).toBe(false);
    expect(result.current.persistence.historyVersion).toBeNull();
    expect(result.current.session.document?.title).toBe("Loaded current title");
  });

  it("keeps the visible history snapshot when selecting it again", async () => {
    const selected = createResumeDetailItem();
    const { result } = renderSave({
      version: async () => detail(selected, "version-old"),
    });
    await act(() => result.current.persistence.selectVersion("version-old"));
    const snapshot = result.current.persistence.historyVersion;
    await act(() => result.current.persistence.selectVersion("version-old"));
    expect(fetchResumeVersionApi).toHaveBeenCalledOnce();
    expect(result.current.persistence.historyVersion).toBe(snapshot);
    expect(result.current.persistence.isVersionLoading).toBe(false);
  });

  it.each([false, true])(
    "waits for the historical document language before publishing its preview (cancelled=%s)",
    async (cancelled) => {
      const messages = deferred<i18n.AppMessages>();
      const loader = vi
        .spyOn(i18n, "loadMessages")
        .mockReturnValueOnce(messages.promise);
      const selected = {
        ...createResumeDetailItem(),
        documentLocale: "zh" as const,
      };
      const { result } = renderSave({
        version: async () => detail(selected, "version-old"),
      });
      let switching!: Promise<void>;
      await act(async () => {
        switching = result.current.persistence.selectVersion("version-old");
      });
      expect(result.current.persistence.historyVersion).toBeNull();
      expect(result.current.persistence.isVersionLoading).toBe(true);
      expect(loader).toHaveBeenCalledWith("zh");
      if (cancelled) act(() => result.current.persistence.returnToLatest());
      await act(async () => {
        messages.resolve(defaultMessages);
        await switching;
      });
      expect(result.current.persistence.historyVersion?.resume ?? null).toEqual(
        cancelled ? null : selected,
      );
      expect(result.current.persistence.isVersionLoading).toBe(false);
    },
  );

  it("preserves input entered while a historical version is loading", async () => {
    const gate = deferred<ResumeDetailResponse>();
    const { result, edit } = renderSave({ version: () => gate.promise });
    let switching!: Promise<void>;
    act(() => {
      switching = result.current.persistence.selectVersion("version-old");
    });
    edit({
      ...createResumeDetailItem(),
      title: "Typed during version request",
    });
    await act(async () => {
      gate.resolve(
        detail(
          { ...createResumeDetailItem(), title: "Historical title" },
          "version-old",
        ),
      );
      await switching;
    });
    expect(result.current.session.document?.title).toBe(
      "Typed during version request",
    );
    expect(result.current.persistence.hasUnsavedChanges()).toBe(true);
    expect(result.current.persistence.activeVersionId).toBe("version-a");
    expect(result.current.persistence.isVersionLoading).toBe(false);
  });

  it("restores the viewed snapshot as a new checkpoint only after confirmation", async () => {
    const historical = {
      ...createResumeDetailItem(),
      title: "Historical title",
    };
    const gate = deferred<ResumeDetailResponse>();
    const fixture = renderSave({
      version: async () => detail(historical, "version-old"),
      save: () => gate.promise,
    });
    await act(() =>
      fixture.result.current.persistence.selectVersion("version-old"),
    );
    let restoring!: Promise<boolean>;
    act(() => {
      restoring = fixture.result.current.persistence.restoreVersion();
    });
    expect(fixture.result.current.persistence.isRestoringVersion).toBe(true);
    expect(fixture.result.current.session.document?.title).toBe(
      "Original title",
    );
    expect(fixture.result.current.persistence.activeVersionId).toBe(
      "version-a",
    );
    expect(saveResumeApi).toHaveBeenCalledExactlyOnceWith(
      historical.id,
      expect.objectContaining({ title: "Historical title" }),
      "checkpoint",
      { notifyOnError: false },
    );
    let restored!: boolean;
    await act(async () => {
      gate.resolve(
        detail({ ...historical, updatedAt: "restored" }, "version-restored"),
      );
      restored = await restoring;
    });
    expect(restored).toBe(true);
    expect(fixture.result.current.persistence.isViewingHistory).toBe(false);
    expect(fixture.result.current.persistence.isRestoringVersion).toBe(false);
    expect(fixture.result.current.session.document?.title).toBe(
      "Historical title",
    );
    expect(fixture.result.current.persistence.activeVersionId).toBe(
      "version-restored",
    );
    expect(fixture.result.current.persistence.hasUnsavedChanges()).toBe(false);
  });

  it("keeps a failed restore available to retry without changing the formal document", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const historical = {
      ...createResumeDetailItem(),
      title: "Retry historical title",
    };
    const fixture = renderSave({
      version: async () => detail(historical, "version-old"),
    });
    await act(() =>
      fixture.result.current.persistence.selectVersion("version-old"),
    );
    vi.mocked(saveResumeApi).mockRejectedValueOnce(new Error("Offline"));
    await act(async () => {
      expect(await fixture.result.current.persistence.restoreVersion()).toBe(
        false,
      );
    });
    expect(fixture.result.current.persistence.hasVersionRestoreError).toBe(
      true,
    );
    expect(fixture.result.current.persistence.historyVersion?.resume).toEqual(
      historical,
    );
    expect(fixture.result.current.session.document?.title).toBe(
      "Original title",
    );
    expect(fixture.result.current.persistence.activeVersionId).toBe(
      "version-a",
    );
    await act(async () => {
      expect(await fixture.result.current.persistence.restoreVersion()).toBe(
        true,
      );
    });
    expect(fixture.result.current.persistence.hasVersionRestoreError).toBe(
      false,
    );
    expect(fixture.result.current.persistence.historyVersion).toBeNull();
    expect(fixture.result.current.session.document?.title).toBe(
      "Retry historical title",
    );
    expect(saveResumeApi).toHaveBeenCalledTimes(2);
  });

  it("cancels a pending history read before restoring the version currently visible", async () => {
    const first = { ...createResumeDetailItem(), title: "Visible history" };
    const second = { ...first, title: "Pending history" };
    const readGate = deferred<ResumeDetailResponse>();
    const saveGate = deferred<ResumeDetailResponse>();
    const fixture = renderSave({
      version: async (_resumeId, versionId) =>
        versionId === "first" ? detail(first, "first") : readGate.promise,
      save: () => saveGate.promise,
    });
    await act(() => fixture.result.current.persistence.selectVersion("first"));
    let reading!: Promise<void>;
    let restoring!: Promise<boolean>;
    act(() => {
      reading = fixture.result.current.persistence.selectVersion("second");
      restoring = fixture.result.current.persistence.restoreVersion();
    });
    const signal = vi
      .mocked(fetchResumeVersionApi)
      .mock.calls.at(-1)?.[2]?.signal;
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      readGate.resolve(detail(second, "second"));
      await reading;
    });
    expect(
      fixture.result.current.persistence.historyVersion?.resume.title,
    ).toBe("Visible history");
    await act(async () => {
      saveGate.resolve(detail(first, "restored"));
      await restoring;
    });
    expect(fixture.result.current.session.document?.title).toBe(
      "Visible history",
    );
  });

  it("aborts historical reads on unmount and never hydrates a late response", async () => {
    const gate = deferred<ResumeDetailResponse>();
    const { result, unmount, hydrate } = renderSave({
      version: () => gate.promise,
    });
    let switching!: Promise<void>;
    act(() => {
      switching = result.current.persistence.selectVersion("version-old");
    });
    const signal = vi.mocked(fetchResumeVersionApi).mock.calls[0][2]?.signal;
    const originalDocument = result.current.session.document;
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      gate.resolve(
        detail(
          { ...createResumeDetailItem(), title: "Historical title" },
          "version-old",
        ),
      );
      await switching;
    });
    expect(result.current.session.document).toBe(originalDocument);
    expect(result.current.session.document?.title).toBe("Original title");
    expect(hydrate).not.toHaveBeenCalled();
  });

  it("reuses fingerprints and diffs across 20 unrelated renders and advances its synchronous baseline", async () => {
    const { result, rerender, edit } = renderSave();
    edit({ ...createResumeDetailItem(), title: "Edited title" });
    const fingerprints = vi.mocked(createResumeFingerprint).mock.calls.length;
    const diffs = vi.mocked(countResumeChanges).mock.calls.length;
    for (let index = 0; index < 20; index += 1) {
      rerender();
      expect(result.current.persistence.hasUnsavedChanges()).toBe(true);
      expect(result.current.persistence.changeCount).toBe(1);
    }
    expect(createResumeFingerprint).toHaveBeenCalledTimes(fingerprints);
    expect(countResumeChanges).toHaveBeenCalledTimes(diffs);
    await act(async () => {
      await result.current.persistence.save();
      expect(result.current.persistence.hasUnsavedChanges()).toBe(false);
    });
    expect(result.current.persistence.changeCount).toBe(0);
    expect(result.current.persistence.activeVersionId).toBe("version-2");
    expect(result.current.persistence.lastSavedAt).toBe("saved-1");
  });
});

it("reuses large template fingerprints and diffs until a document edit", async () => {
  const initial = createResumeDetailTemplate("template-performance", {
    name: "Original template",
  });
  initial.layout.images = [
    {
      id: "image-a",
      name: "Image",
      src: "data:image/png;base64," + "a".repeat(200_000),
      alt: "",
      x: 10,
      y: 10,
      width: 100,
      height: 100,
      opacity: 1,
      borderWidth: 0,
      borderColor: "#000000",
      borderRadius: 0,
      objectFit: "contain",
      visible: true,
    },
  ];
  vi.mocked(saveTemplateApi).mockImplementation(async (_id, snapshot) => ({
    template: {
      ...initial,
      ...snapshot,
      updatedAt: "2026-09-01T00:00:01.000Z",
    },
    checkpoint: null,
  }));
  const { result, rerender } = renderHook(() => {
    const [template, setTemplate] = useState(initial);
    const persistence = useTemplateDetailSave({
      initialCheckpoint: null,
      isLoading: false,
      messages: defaultMessages,
      template,
      onAdoptSavedTemplate(saved, accepted) {
        setTemplate((current) =>
          accepted.has(tracking.createTemplateFingerprint(current))
            ? saved
            : current,
        );
      },
      onRestoreTemplate: setTemplate,
    });
    return { persistence, setTemplate };
  });
  const fingerprints = vi.mocked(createTemplateFingerprint).mock.calls.length;
  const diffs = vi.mocked(countTemplateChanges).mock.calls.length;
  for (let index = 0; index < 20; index += 1) {
    rerender();
    expect(result.current.persistence.hasUnsavedChanges()).toBe(false);
  }
  expect(createTemplateFingerprint).toHaveBeenCalledTimes(fingerprints);
  expect(countTemplateChanges).toHaveBeenCalledTimes(diffs);
  act(() =>
    result.current.setTemplate((current) => ({
      ...current,
      layout: {
        ...current.layout,
        images: [{ ...current.layout.images[0], x: 15 }],
      },
    })),
  );
  expect(createTemplateFingerprint).toHaveBeenCalledTimes(fingerprints + 1);
  expect(countTemplateChanges).toHaveBeenCalledTimes(diffs + 1);
  expect(result.current.persistence.hasUnsavedChanges()).toBe(true);
  expect(result.current.persistence.changeCount).toBe(1);
  await act(async () => {
    await result.current.persistence.save();
    expect(result.current.persistence.hasUnsavedChanges()).toBe(false);
  });
  rerender();
  expect(result.current.persistence.changeCount).toBe(0);
});
