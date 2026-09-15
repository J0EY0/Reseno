import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useResumeDetailExport } from "@/components/workspace/use-resume-detail-export";
import { useResumeDetailSave } from "@/components/workspace/use-resume-detail-save";
import { useResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import { defaultMessages } from "@/i18n";
import { notifyApiError } from "@/lib/api-error-notifier";
import { createResumeArtifact, downloadResumeJson } from "@/lib/export-api";
import { createEmptyResume } from "@/lib/resume";
import { fetchResumeVersionsApi, saveResumeApi } from "@/lib/workspace-api";
import type { ResumeArtifactV1, ResumeDetailResponse } from "@/types/api";

import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

vi.mock("@/hooks/use-auth-session-token", () => ({
  useAuthSessionToken: () => "session-token",
}));
vi.mock("sonner", () => ({
  toast: { dismiss: vi.fn(), error: vi.fn(), success: vi.fn() },
}));
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
}));
vi.mock("@/lib/export-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/export-api")>()),
  downloadResumeJson: vi.fn(),
}));

beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }));
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it.each([false, true])(
  "exports its own checkpoint and matching custom template when queued=%s",
  async (queued) => {
    const initial = createResumeDetailItem({ resume: createEmptyResume() });
    const savedResume = { ...initial, template: "custom-a" };
    const checkpoint = { savedAt: initial.updatedAt, versionId: "version-a" };
    let resolveSave!: (value: ResumeDetailResponse) => void;
    const gate = new Promise<ResumeDetailResponse>((resolve) => {
      resolveSave = resolve;
    });
    const downloads: ResumeArtifactV1[] = [];
    vi.mocked(downloadResumeJson).mockImplementation((resume, template) => {
      downloads.push(createResumeArtifact(resume, template));
    });
    vi.mocked(saveResumeApi).mockImplementation(async (_id, payload) => {
      const count = vi.mocked(saveResumeApi).mock.calls.length;
      return count === 1
        ? gate
        : {
            resume: { ...initial, ...payload, updatedAt: `saved-${count}` },
            savedAt: `saved-${count}`,
            versionId: `version-${count + 1}`,
          };
    });
    vi.mocked(fetchResumeVersionsApi).mockResolvedValue({
      versions: [checkpoint],
    });

    const templates = ["custom-a", "custom-b"].map((id) =>
      createResumeDetailTemplate(id, { updatedAt: initial.updatedAt }),
    );
    const { result, rerender } = renderHook(() => {
      const session = useResumeDetailSession({ initialResume: initial });
      const persistence = useResumeDetailSave({
        getFingerprint: session.getFingerprint,
        getSnapshot: session.getSnapshot,
        initialCheckpoint: checkpoint,
        initialResume: initial,
        isLoading: false,
        liveFingerprint: session.fingerprint,
        liveResume: session.document,
        messages: defaultMessages,
        onAdoptSavedResume: session.adoptSavedResume,
        onHydrateResume: session.hydrate,
        resumeId: initial.id,
      });
      const exporting = useResumeDetailExport({
        messages: defaultMessages,
        save: () => persistence.save(),
        templates,
      });
      return { session, persistence, exporting };
    });
    act(() => result.current.session.hydrate(savedResume));
    let autosaving: Promise<ResumeDetailResponse> | null = null;
    let exporting!: Promise<void>;
    act(() => {
      if (queued) autosaving = result.current.persistence.save("autosave");
      exporting = result.current.exporting.exportJson();
    });
    const newerResume = {
      ...savedResume,
      title: "Typed during export",
      template: "custom-b",
    };
    act(() => result.current.session.hydrate(newerResume));
    rerender();
    await act(async () => {
      resolveSave({ resume: savedResume, ...checkpoint });
      await autosaving;
      await exporting;
    });
    const exportedResume = queued ? newerResume : savedResume;
    expect(downloads).toHaveLength(1);
    expect(downloads[0].resumes[0].title).toBe(exportedResume.title);
    expect(downloads[0].templates[0].definition.name).toBe(
      exportedResume.template,
    );
    expect(notifyApiError).not.toHaveBeenCalled();
    expect(result.current.persistence.hasUnsavedChanges()).toBe(!queued);
    expect(result.current.session.document?.template).toBe("custom-b");
  },
);
