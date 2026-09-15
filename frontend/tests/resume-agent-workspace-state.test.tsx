import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useResumeDetailWorkspace } from "@/components/workspace/use-resume-detail-workspace";
import { createResumeDetailRouteHandoff } from "@/lib/workspace-detail-route-handoff";
import { clearWorkspaceRouteMemory } from "@/lib/workspace-route-memory";
import { resolveAgentDraftDecision } from "@/lib/agent-session-run-client";
import {
  fetchResumeApi,
  fetchResumeVersionApi,
  fetchResumeVersionsApi,
  fetchWorkspaceRouteData,
  saveResumeApi,
} from "@/lib/workspace-api";
import type { AgentDraftSnapshot, ResumeDetailResponse } from "@/types/api";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";
import { createResume } from "./helpers/agent-edit-fixtures";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";

vi.mock("@/hooks/use-auth-session-token", () => ({
  useAuthSessionToken: () => "session",
}));
vi.mock("@/components/preview/document-canvas-loader", () => ({
  loadDocumentCanvas: vi.fn(),
}));
vi.mock("@/lib/workspace-api", async (original) => ({
  ...(await original<typeof import("@/lib/workspace-api")>()),
  fetchResumeApi: vi.fn(),
  fetchResumeVersionApi: vi.fn(),
  fetchResumeVersionsApi: vi.fn(),
  fetchWorkspaceRouteData: vi.fn(),
  saveResumeApi: vi.fn(),
}));
vi.mock("@/lib/agent-session-run-client", async (original) => ({
  ...(await original<typeof import("@/lib/agent-session-run-client")>()),
  resolveAgentDraftDecision: vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: {
    dismiss: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));
const disposers: (() => void)[] = [];
function fixture() {
  const workspace = createWorkspaceFixture({ path: "/resume/resume-a" });
  disposers.push(() => workspace.router.dispose());
  const initial = createResumeDetailItem({ resume: createResume() });
  const prepared: PreparedResumeDetailRouteData = {
    detail: { resume: initial, savedAt: initial.updatedAt, versionId: "v1" },
    routeData: {
      customTemplates: [],
      defaultTemplateIds: { en: "minimal", zh: "minimal" },
      modelConfigs: [],
      agentSettings: workspace.preferences.agentSettings!,
    },
    versions: [{ versionId: "v1", savedAt: initial.updatedAt }],
  };
  const routeState = createResumeDetailRouteHandoff(prepared, 1, 1);
  const hook = renderHook(
    () =>
      useResumeDetailWorkspace({
        locale: "en",
        messages: workspace.preferences.messages,
        resumeId: initial.id,
        routeState,
        onLogout: vi.fn(),
      }),
    { wrapper: workspace.wrapper },
  );
  const snapshot: AgentDraftSnapshot = {
    baseResume: initial.resume,
    sourceMessageId: "draft-message",
    transactionState: "committed",
    edits: [
      {
        id: "edit-headline",
        title: "Headline",
        reason: "Requested title",
        target: "basic.headline",
        operation: {
          type: "replace_field",
          path: "basic.headline",
          value: "Agent headline",
        },
      },
    ],
    reviewItems: [
      { id: "review-headline", editIds: ["edit-headline"], status: "pending" },
    ],
  };
  vi.mocked(fetchResumeVersionsApi).mockResolvedValue({
    versions: prepared.versions,
  });
  return { ...hook, initial, prepared, snapshot };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});
afterEach(() => {
  cleanup();
  disposers.splice(0).forEach((dispose) => dispose());
  clearWorkspaceRouteMemory();
  localStorage.clear();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

it("projects suggestions in preview while saving only the latest formal editor content", async () => {
  const f = fixture();
  act(() =>
    f.result.current.model.commands.agent.previewEdits(
      f.snapshot.edits,
      f.initial.resume,
      f.snapshot.sourceMessageId,
      "provisional",
    ),
  );
  act(() =>
    f.result.current.model.commands.updateContent((current) => ({
      ...current,
      basic: { ...current.basic, name: "Manual editor name" },
    })),
  );
  expect(f.result.current.model.state.previewResume.basic.headline).toBe(
    "Agent headline",
  );
  expect(f.result.current.model.state.previewResume.basic.name).toBe(
    "Manual editor name",
  );
  expect(f.result.current.model.state.resume.basic.headline).toBe("Engineer");
  vi.mocked(saveResumeApi).mockImplementation(async (_id, payload) => ({
    resume: { ...f.initial, ...payload },
    savedAt: "saved",
    versionId: "v2",
  }));
  await act(async () => f.result.current.model.commands.save());
  expect(saveResumeApi).toHaveBeenCalledTimes(1);
  const saved = vi.mocked(saveResumeApi).mock.calls[0][1].resume;
  expect(saved.basic.name).toBe("Manual editor name");
  expect(saved.basic.headline).toBe("Engineer");
  expect(f.result.current.model.state.agent.draftState).not.toBeNull();
});

it.each(["applied", "discarded"] as const)(
  "connects $0 decisions to persistence with current editor state and formal adoption rules",
  async (status) => {
    const f = fixture();
    act(() => f.result.current.model.commands.agent.reconcileDraft(f.snapshot));
    act(() =>
      f.result.current.model.commands.updateContent((current) => ({
        ...current,
        basic: { ...current.basic, name: "Unsaved manual name" },
      })),
    );
    const current = f.result.current.model.state.resume;
    const authoritative = {
      ...f.initial,
      resume: {
        ...current,
        basic: { ...current.basic, headline: "Server authoritative headline" },
      },
    };
    vi.mocked(resolveAgentDraftDecision).mockResolvedValue({
      committed: true,
      resolvedAsRequested: true,
      resume: { resume: authoritative, savedAt: "server", versionId: "v2" },
      draft: {
        baseResume: f.initial.resume,
        reviewItems: [{ ...f.snapshot.reviewItems[0], status }],
      },
      session: {
        resumeId: f.initial.id,
        revision: "r2",
        messages: [],
        executions: [],
      },
    });
    await act(async () => {
      if (status === "applied")
        await f.result.current.model.commands.agent.applyDraft();
      else await f.result.current.model.commands.agent.discardDraft();
    });
    expect(resolveAgentDraftDecision).toHaveBeenCalledExactlyOnceWith(
      f.initial.id,
      "draft-message",
      status === "applied"
        ? {
            conflictResolution: undefined,
            currentResume: current,
            currentVersionId: "v1",
            rebaseOnLatest: false,
            reviewItemIds: ["review-headline"],
            status,
          }
        : { reviewItemIds: ["review-headline"], status },
    );
    expect(f.result.current.model.state.resume.basic.name).toBe(
      "Unsaved manual name",
    );
    expect(f.result.current.model.state.resume.basic.headline).toBe(
      status === "applied" ? "Server authoritative headline" : "Engineer",
    );
    expect(f.result.current.model.state.agent.draftState).toBeNull();
    expect(f.result.current.model.state.previewResume).toEqual(
      f.result.current.model.state.resume,
    );
    expect(saveResumeApi).not.toHaveBeenCalled();
  },
);

it.each(["route refresh", "history selection"] as const)(
  "clears the Agent transaction and selection when %s hydrates a formal document",
  async (source) => {
    const f = fixture();
    act(() => f.result.current.model.commands.agent.reconcileDraft(f.snapshot));
    act(() => f.result.current.model.state.agent.review!.selectFirst());
    expect(f.result.current.model.state.agent.review!.mode).toBe("single");
    const fresh: ResumeDetailResponse = {
      resume: {
        ...f.initial,
        resume: {
          ...f.initial.resume,
          basic: {
            ...f.initial.resume.basic,
            headline: "Hydrated formal headline",
          },
        },
      },
      savedAt: "fresh",
      versionId: "v3",
    };
    if (source === "route refresh") {
      vi.mocked(fetchResumeApi).mockResolvedValue(fresh);
      vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
        kind: "resume-detail",
        data: f.prepared.routeData,
      });
      act(() => f.result.current.model.commands.retryLoad());
      await act(() => vi.advanceTimersByTimeAsync(0));
    } else {
      vi.mocked(fetchResumeVersionApi).mockResolvedValue(fresh);
      await act(async () =>
        f.result.current.model.commands.selectVersion("v3"),
      );
    }
    expect(f.result.current.model.state.resume.basic.headline).toBe(
      "Hydrated formal headline",
    );
    expect(f.result.current.model.state.agent.draft).toBeNull();
    expect(f.result.current.model.state.agent.draftState).toBeNull();
    expect(f.result.current.model.state.previewReview).toBeNull();
    expect(f.result.current.model.state.previewResume).toEqual(
      f.result.current.model.state.resume,
    );
    act(() =>
      f.result.current.model.commands.agent.previewEdits(
        f.snapshot.edits,
        fresh.resume.resume,
        "new-message",
        "committed",
      ),
    );
    expect(f.result.current.model.state.agent.review!.mode).toBe("all");
    expect(
      f.result.current.model.state.agent.review!.resolvingStatus,
    ).toBeNull();
    expect(
      f.result.current.model.state.agent.review!.exitingReviewItemIds,
    ).toEqual([]);
  },
);
