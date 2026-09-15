import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { useResumeAgentDraft } from "@/hooks/use-resume-agent-draft";
import { defaultMessages } from "@/i18n";
import { notifyApiError } from "@/lib/api-error-notifier";
import type { AgentDraftDecisionResolution } from "@/lib/agent-session-run-client";
import type {
  AgentDraftSnapshot,
  AgentResumeEditSuggestion,
} from "@/types/api";
import { createResume } from "./helpers/agent-edit-fixtures";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/api-error-notifier", () => ({ notifyApiError: vi.fn() }));

function fixture() {
  const baseResume = createResume();
  const edits: AgentResumeEditSuggestion[] = (
    ["headline", "summary"] as const
  ).map((field) => ({
    id: `edit-${field}`,
    title: field,
    target: `basic.${field}`,
    reason: "Requested update",
    operation: {
      type: "replace_field",
      path: `basic.${field}`,
      value: `Agent ${field}`,
    },
  }));
  edits.push({
    id: "edit-education",
    title: "Education",
    target: "sections[education]",
    reason: "Requested title",
    operation: {
      type: "update_section",
      sectionId: "education",
      patch: { title: "Academic background" },
    },
  });
  const snapshot: AgentDraftSnapshot = {
    baseResume,
    edits,
    sourceMessageId: "message-a",
    transactionState: "committed",
    reviewItems: edits.map((edit) => ({
      id: `review-${edit.id}`,
      editIds: [edit.id],
      status: "pending",
    })),
  };
  const onApplyResume = vi.fn();
  const onResolveDraftReview =
    vi.fn<Parameters<typeof useResumeAgentDraft>[0]["onResolveDraftReview"]>();
  const props = {
    resume: baseResume,
    resumeId: "resume-a",
    messages: defaultMessages,
    onApplyResume,
    onResolveDraftReview,
  };
  const hook = renderHook((input) => useResumeAgentDraft(input), {
    initialProps: props,
  });
  return {
    ...hook,
    props,
    baseResume,
    edits,
    snapshot,
    onApplyResume,
    onResolveDraftReview,
  };
}
function receipt(
  snapshot: AgentDraftSnapshot,
  ids: string[],
  status: "applied" | "discarded",
): AgentDraftDecisionResolution {
  const draft = {
    baseResume: snapshot.baseResume,
    reviewItems: snapshot.reviewItems.map((item) =>
      ids.includes(item.id) ? { ...item, status } : item,
    ),
  };
  const authoritative = {
    ...createResumeDetailItem(),
    resume: {
      ...snapshot.baseResume,
      basic: { ...snapshot.baseResume.basic, name: "Server authority" },
    },
  };
  return {
    committed: true,
    resolvedAsRequested: true,
    draft,
    resume:
      status === "applied"
        ? { resume: authoritative, savedAt: "saved", versionId: "v2" }
        : null,
    session: {
      resumeId: "resume-a",
      revision: "r2",
      executions: [],
      messages: [
        {
          id: snapshot.sourceMessageId,
          role: "assistant",
          text: "Reviewed",
          createdAt: "2026-01-01",
          response: {
            id: snapshot.sourceMessageId,
            role: "assistant",
            text: "Reviewed",
            edits: snapshot.edits,
            transactionState: "committed",
            draft,
          },
        },
      ],
    },
  };
}
async function advance(ms: number) {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false })),
  );
});
afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

describe("Agent draft hook ownership", () => {
  it("projects against the latest editor resume and preserves creation time for replacement batches", () => {
    const f = fixture();
    act(() =>
      f.result.current.previewAgentEdits(
        f.edits,
        f.baseResume,
        "message-a",
        "provisional",
      ),
    );
    const createdAt = f.result.current.agentDraft!.createdAt;
    const latest = {
      ...f.baseResume,
      basic: { ...f.baseResume.basic, name: "Manual name" },
    };
    f.rerender({ ...f.props, resume: latest });
    expect(f.result.current.agentDraft!.resume.basic.name).toBe("Manual name");
    expect(f.result.current.agentDraft!.resume.basic.headline).toBe(
      "Agent headline",
    );
    vi.setSystemTime(new Date("2026-01-02T00:00:00Z"));
    act(() =>
      f.result.current.previewAgentEdits(
        f.edits,
        f.baseResume,
        "message-a",
        "committed",
      ),
    );
    expect(f.result.current.agentDraft!.createdAt).toBe(createdAt);
    expect(f.result.current.agentDraft!.updatedAt).toBe(
      "2026-01-02T00:00:00.000Z",
    );
    expect(f.result.current.agentDraft!.resume.basic.name).toBe("Manual name");
    expect(f.onApplyResume).not.toHaveBeenCalled();
    act(() =>
      f.result.current.previewAgentEdits(
        f.edits,
        latest,
        "message-b",
        "committed",
      ),
    );
    expect(f.result.current.agentDraft!.createdAt).toBe(
      "2026-01-02T00:00:00.000Z",
    );
  });

  it.each(["provisional", "committed"] as const)(
    "only a committed invalid or empty replacement clears a %s draft",
    (state) => {
      const f = fixture();
      act(() =>
        f.result.current.previewAgentEdits(
          f.edits,
          f.baseResume,
          "message-a",
          state,
        ),
      );
      const malformed = [
        {
          ...f.edits[0],
          operation: {
            type: "replace_field",
            path: "basic.missing",
            value: "Invalid",
          },
        },
      ] as unknown as AgentResumeEditSuggestion[];
      for (const replacement of [malformed, []]) {
        act(() =>
          f.result.current.previewAgentEdits(
            replacement,
            f.baseResume,
            "message-a",
            "provisional",
          ),
        );
        expect(f.result.current.agentDraft).not.toBeNull();
      }
      expect(toast.error).not.toHaveBeenCalled();
      act(() =>
        f.result.current.previewAgentEdits(
          malformed,
          f.baseResume,
          "message-other",
          "committed",
        ),
      );
      expect(f.result.current.agentDraft!.sourceMessageId).toBe("message-a");
      act(() =>
        f.result.current.previewAgentEdits(
          malformed,
          f.baseResume,
          "message-a",
          "committed",
        ),
      );
      expect(f.result.current.agentDraft).toBeNull();
      expect(toast.error).toHaveBeenCalledWith(
        defaultMessages.agentDraftBatchRejected,
        expect.objectContaining({
          closeButton: true,
          description: expect.any(String),
        }),
      );
      act(() =>
        f.result.current.previewAgentEdits(
          f.edits,
          f.baseResume,
          "message-a",
          state,
        ),
      );
      act(() =>
        f.result.current.previewAgentEdits(
          [],
          f.baseResume,
          "message-a",
          "committed",
        ),
      );
      expect(f.result.current.agentDraftState).toBeNull();
    },
  );

  it("keeps editable conflicts reviewable and rejects decisions on provisional batches", async () => {
    const f = fixture();
    const current = {
      ...f.baseResume,
      basic: { ...f.baseResume.basic, headline: "Manual headline" },
    };
    f.rerender({ ...f.props, resume: current });
    act(() =>
      f.result.current.previewAgentEdits(
        f.edits,
        f.baseResume,
        "message-a",
        "provisional",
      ),
    );
    await act(async () => {
      expect(await f.result.current.applyAgentDraft()).toBeNull();
      expect(await f.result.current.discardAgentDraft()).toBeNull();
    });
    expect(f.result.current.review).toBeNull();
    expect(f.onResolveDraftReview).not.toHaveBeenCalled();
    act(() => f.result.current.reconcileAgentDraft(f.snapshot));
    expect(f.result.current.review!.allConflicts.length).toBeGreaterThan(0);
    expect(f.result.current.agentDraftState!.pendingCount).toBe(3);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it.each(["reset", "new draft"] as const)(
    "ignores an old decision after %s and resets selection and resolving state",
    async (change) => {
      const f = fixture();
      const pending = Promise.withResolvers<AgentDraftDecisionResolution>();
      f.onResolveDraftReview.mockReturnValueOnce(pending.promise);
      act(() => f.result.current.reconcileAgentDraft(f.snapshot));
      act(() => f.result.current.review!.selectFirst());
      await advance(180);
      let decision: Promise<unknown> | undefined;
      act(() => {
        decision = f.result.current.applyAgentDraft();
      });
      expect(f.result.current.review!.resolvingStatus).toBe("applied");
      act(() => f.result.current.resetAgentDraft());
      expect(f.result.current.agentDraft).toBeNull();
      expect(f.result.current.review).toBeNull();
      if (change === "new draft")
        act(() =>
          f.result.current.reconcileAgentDraft({
            ...f.snapshot,
            sourceMessageId: "new-message",
          }),
        );
      await act(async () => {
        pending.resolve(
          receipt(f.snapshot, [f.snapshot.reviewItems[0].id], "applied"),
        );
        await vi.advanceTimersByTimeAsync(180);
        await decision;
      });
      expect(f.onApplyResume).not.toHaveBeenCalled();
      expect(toast.success).not.toHaveBeenCalled();
      if (change === "new draft") {
        expect(f.result.current.agentDraft!.sourceMessageId).toBe(
          "new-message",
        );
        expect(f.result.current.review!.mode).toBe("all");
        expect(f.result.current.review!.resolvingStatus).toBeNull();
        expect(f.result.current.review!.exitingReviewItemIds).toEqual([]);
      } else expect(f.result.current.agentDraftState).toBeNull();
    },
  );
});

describe("Agent draft review decisions", () => {
  it.each(
    (["all", "single"] as const).flatMap((scope) =>
      (["applied", "discarded"] as const).map((status) => ({ scope, status })),
    ),
  )(
    "persists the exact $scope scope as $status, waits for exit, and adopts the authoritative result",
    async ({ scope, status }) => {
      const f = fixture();
      act(() => f.result.current.reconcileAgentDraft(f.snapshot));
      if (scope === "single") {
        act(() => f.result.current.review!.selectFirst());
        await advance(180);
      }
      const current = {
        ...f.baseResume,
        basic: { ...f.baseResume.basic, name: "Latest manual" },
      };
      f.rerender({ ...f.props, resume: current });
      const ids = (
        scope === "single"
          ? f.snapshot.reviewItems.slice(0, 1)
          : f.snapshot.reviewItems
      ).map((item) => item.id);
      const response = receipt(f.snapshot, ids, status);
      const pending = Promise.withResolvers<AgentDraftDecisionResolution>();
      f.onResolveDraftReview.mockReturnValue(pending.promise);
      let decision: Promise<unknown> | undefined;
      act(() => {
        decision =
          status === "applied"
            ? f.result.current.applyAgentDraft()
            : f.result.current.discardAgentDraft();
      });
      expect(f.onResolveDraftReview).toHaveBeenCalledExactlyOnceWith(
        "message-a",
        current,
        ids,
        status,
        undefined,
      );
      expect(f.result.current.review!.disabled).toBe(true);
      expect(f.result.current.review!.exitingReviewItemIds).toEqual(ids);
      expect(f.result.current.review!.resolvingStatus).toBe(status);
      await act(async () => {
        expect(await f.result.current.applyAgentDraft()).toBeNull();
        pending.resolve(response);
      });
      await advance(179);
      expect(f.result.current.review!.resolvingStatus).toBe(status);
      expect(f.onApplyResume).not.toHaveBeenCalled();
      await advance(1);
      expect(await decision).toBe(response.session);
      expect(f.onApplyResume).toHaveBeenCalledTimes(
        status === "applied" ? 1 : 0,
      );
      if (status === "applied")
        expect(f.onApplyResume).toHaveBeenCalledWith(
          response.resume!.resume.resume,
        );
      expect(toast.success).toHaveBeenCalledExactlyOnceWith(
        status === "applied"
          ? defaultMessages.agentDraftApplied
          : defaultMessages.agentDraftDiscarded,
        { closeButton: true },
      );
      if (scope === "single") {
        expect(f.result.current.review!.selectedItemId).toBe(
          f.snapshot.reviewItems[1].id,
        );
        expect(f.result.current.review!.pendingCount).toBe(2);
        expect(f.result.current.review!.exitingReviewItemIds).toEqual([]);
        expect(f.result.current.review!.resolvingStatus).toBeNull();
      } else {
        expect(f.result.current.review).toBeNull();
        expect(f.result.current.agentDraftState).toBeNull();
      }
    },
  );

  it("keeps the decision locked after exit completes until persistence settles", async () => {
    const f = fixture();
    act(() => f.result.current.reconcileAgentDraft(f.snapshot));
    const pending = Promise.withResolvers<AgentDraftDecisionResolution>();
    f.onResolveDraftReview.mockReturnValue(pending.promise);
    let decision: Promise<unknown> | undefined;
    act(() => {
      decision = f.result.current.discardAgentDraft();
    });
    await advance(180);
    expect(f.result.current.review!.resolvingStatus).toBe("discarded");
    expect(f.result.current.agentDraftState!.pendingCount).toBe(3);
    await act(async () => {
      pending.resolve(
        receipt(
          f.snapshot,
          f.snapshot.reviewItems.map((item) => item.id),
          "discarded",
        ),
      );
      await decision;
    });
    expect(f.result.current.agentDraftState).toBeNull();
  });

  it.each(["applyOriginal", "keepManual"] as const)(
    "%s resolves the whole draft even from single-item mode",
    async (command) => {
      const f = fixture();
      act(() => f.result.current.reconcileAgentDraft(f.snapshot));
      act(() => f.result.current.review!.selectFirst());
      await advance(180);
      const ids = f.snapshot.reviewItems.map((item) => item.id);
      f.onResolveDraftReview.mockResolvedValue(
        receipt(f.snapshot, ids, "applied"),
      );
      let decision: Promise<unknown> | undefined;
      act(() => {
        decision = f.result.current.review![command]();
      });
      expect(f.onResolveDraftReview).toHaveBeenCalledExactlyOnceWith(
        "message-a",
        f.baseResume,
        ids,
        "applied",
        command === "applyOriginal" ? "use-original" : "keep-manual",
      );
      await advance(180);
      await decision;
      expect(f.result.current.agentDraftState).toBeNull();
    },
  );

  it.each(["failure", "abort"] as const)(
    "clears decision exit state on %s while retaining the reviewable draft",
    async (failure) => {
      const f = fixture();
      act(() => f.result.current.reconcileAgentDraft(f.snapshot));
      const error =
        failure === "abort"
          ? new DOMException("Aborted", "AbortError")
          : new Error("Decision failed");
      vi.spyOn(console, "error").mockImplementation(() => undefined);
      f.onResolveDraftReview.mockRejectedValue(error);
      await act(async () => {
        expect(await f.result.current.applyAgentDraft()).toBeNull();
      });
      expect(f.result.current.review!.disabled).toBe(false);
      expect(f.result.current.review!.resolvingStatus).toBeNull();
      expect(f.result.current.review!.exitingReviewItemIds).toEqual([]);
      expect(f.result.current.agentDraftState!.pendingCount).toBe(3);
      expect(notifyApiError).toHaveBeenCalledTimes(failure === "abort" ? 0 : 1);
      if (failure === "failure")
        expect(notifyApiError).toHaveBeenCalledWith(
          error,
          defaultMessages.agentRequestFailed,
        );
    },
  );
});

it.each([false, true])(
  "preserves disappearing regions for all-to-single selection with reduced motion=%s",
  async (reduced) => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: reduced })),
    );
    const f = fixture();
    act(() => f.result.current.reconcileAgentDraft(f.snapshot));
    act(() =>
      f.result.current.review!.selectItem(f.snapshot.reviewItems[1].id),
    );
    if (!reduced) {
      expect(f.result.current.review!.mode).toBe("all");
      expect(f.result.current.review!.exitingReviewItemIds).toEqual([
        f.snapshot.reviewItems[0].id,
        f.snapshot.reviewItems[2].id,
      ]);
      await act(async () => {
        expect(await f.result.current.applyAgentDraft()).toBeNull();
      });
      expect(f.onResolveDraftReview).not.toHaveBeenCalled();
      await advance(179);
      expect(f.result.current.review!.mode).toBe("all");
      await advance(1);
    }
    expect(f.result.current.review!.mode).toBe("single");
    expect(f.result.current.review!.selectedIndex).toBe(1);
    expect(f.result.current.review!.exitingReviewItemIds).toEqual([]);
    act(() => f.result.current.review!.selectNext());
    expect(f.result.current.review!.selectedIndex).toBe(2);
    act(() => f.result.current.review!.selectPrevious());
    expect(f.result.current.review!.selectedIndex).toBe(1);
    act(() => f.result.current.review!.showAll());
    expect(f.result.current.review!.mode).toBe("all");
  },
);
