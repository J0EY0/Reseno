// @vitest-environment node
import { beforeEach, expect, it, vi } from "vitest";

import {
  loadResumeDetailRouteData,
  loadTemplateDetailRouteData,
  prepareCreatedResumeDetailRoute,
  prepareResumeDetailRoute,
  prepareTemplateDetailRoute,
  prepareWorkspaceRoute,
  prepareWorkspaceEntry,
} from "@/components/workspace/workspace-route-preparation";
import {
  preloadWorkspaceRoute,
  loadResumeDetailWorkspacePage,
  loadTemplateDetailWorkspacePage,
  loadWorkspacePreferencesProvider,
} from "@/components/workspace/workspace-route-loaders";
import {
  fetchResumeApi,
  fetchResumeVersionsApi,
  fetchWorkspaceRouteData,
  fetchTemplateApi,
} from "@/lib/workspace-api";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  getWorkspaceRouteDataPath,
  type LoadableWorkspaceRouteDataKind,
  type WorkspaceRouteDataResult,
} from "@/lib/workspace-route-data";
import type {
  ResumeDetailResponse,
  WorkspaceVersionSummary,
} from "@/types/api";
import { loadDocumentCanvas } from "@/components/preview/document-canvas-loader";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

vi.mock("@/lib/workspace-api", () => ({
  fetchResumeApi: vi.fn(),
  fetchResumeVersionsApi: vi.fn(),
  fetchWorkspaceRouteData: vi.fn(),
  fetchTemplateApi: vi.fn(),
}));
vi.mock("@/components/workspace/workspace-route-loaders", () => ({
  preloadWorkspaceRoute: vi.fn(),
  loadResumeDetailWorkspacePage: vi.fn(),
  loadTemplateDetailWorkspacePage: vi.fn(),
  loadWorkspacePreferencesProvider: vi.fn(),
}));
vi.mock("@/components/preview/document-canvas-loader", () => ({
  loadDocumentCanvas: vi.fn(),
}));
beforeEach(() => vi.resetAllMocks());

it.each(
  Object.entries({
    "resume-gallery": "/api/workspace/pages/resumes",
    "resume-detail": "/api/workspace/pages/resume-editor",
    "template-gallery": "/api/workspace/pages/templates",
    "template-detail": "/api/workspace/pages/templates",
    trash: "/api/workspace/pages/trash",
    models: "/api/workspace/pages/models",
    settings: "/api/workspace/pages/settings",
    "pdf-export": "/api/workspace/pages/templates",
  }),
)("resolves the %s API endpoint", (kind, path) =>
  expect(
    getWorkspaceRouteDataPath(kind as LoadableWorkspaceRouteDataKind),
  ).toBe(path),
);

it.each(["resume", "settings"] as const)(
  "loads %s modules and data concurrently and publishes only a complete entry",
  async (view) => {
    const signal = new AbortController().signal;
    const module =
      Promise.withResolvers<
        Awaited<ReturnType<typeof preloadWorkspaceRoute>>
      >();
    const data = Promise.withResolvers<WorkspaceRouteDataResult>();
    vi.mocked(preloadWorkspaceRoute).mockReturnValue(module.promise);
    vi.mocked(fetchWorkspaceRouteData).mockReturnValue(data.promise);
    const published = vi.fn();
    const result = prepareWorkspaceEntry(view, { signal }).then(published);
    const kind = view === "resume" ? "resume-gallery" : "settings";
    expect(preloadWorkspaceRoute).toHaveBeenCalledExactlyOnceWith(view);
    expect(fetchWorkspaceRouteData).toHaveBeenCalledExactlyOnceWith(kind, {
      signal,
      notifyOnError: false,
    });
    const routeData = {
      theme: "dark",
      modelConfigs: [],
      agentSettings: normalizeAgentSettings(null),
      resumes: [],
      defaultTemplateIds: { en: "minimal", zh: "minimal" },
      customTemplates: [],
    } as const;
    const payload = {
      ...routeData,
      modelConfigs: [],
      resumes: [],
      customTemplates: [],
    };
    data.resolve(
      view === "resume"
        ? { kind: "resume-gallery", data: payload }
        : { kind: "settings", data: payload },
    );
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(published).not.toHaveBeenCalled();
    module.resolve(
      [] as unknown as Awaited<ReturnType<typeof preloadWorkspaceRoute>>,
    );
    await result;
    expect(published).toHaveBeenCalledExactlyOnceWith({
      view,
      data: routeData,
    });
  },
);

it.each(["cancelled", "failed"])(
  "does not publish a %s workspace entry",
  async (failure) => {
    const controller = new AbortController();
    const data = Promise.withResolvers<WorkspaceRouteDataResult>();
    vi.mocked(preloadWorkspaceRoute).mockResolvedValue(
      [] as unknown as Awaited<ReturnType<typeof preloadWorkspaceRoute>>,
    );
    vi.mocked(fetchWorkspaceRouteData).mockReturnValue(data.promise);
    const entering = prepareWorkspaceEntry("resume", {
      signal: controller.signal,
    });
    const error = new Error("Page preparation failed");
    const assertion =
      failure === "cancelled"
        ? expect(entering).rejects.toMatchObject({ name: "AbortError" })
        : expect(entering).rejects.toBe(error);
    if (failure === "cancelled") {
      controller.abort();
      data.resolve({
        kind: "settings",
        data: { modelConfigs: [], agentSettings: normalizeAgentSettings(null) },
      });
    } else data.reject(error);
    await assertion;
  },
);

it.each(["success", "failed", "aborted"])(
  "waits for queued preferences then loads all detail resources together when history is %s",
  async (outcome) => {
    const flush = Promise.withResolvers<void>();
    const route = Promise.withResolvers<WorkspaceRouteDataResult>();
    const detail = Promise.withResolvers<ResumeDetailResponse>();
    const versions = Promise.withResolvers<{
      versions: WorkspaceVersionSummary[];
    }>();
    vi.mocked(fetchWorkspaceRouteData).mockReturnValue(route.promise);
    vi.mocked(fetchResumeApi).mockReturnValue(detail.promise);
    vi.mocked(fetchResumeVersionsApi).mockReturnValue(versions.promise);
    const accept = vi.fn();
    const persistence = {
      flush: () => flush.promise,
      prepareRead: async () => accept,
    } as unknown as WorkspacePreferencesPersistence;
    const signal = new AbortController().signal;
    const result = loadResumeDetailRouteData("resume-a", persistence, {
      signal,
    });
    expect(fetchResumeApi).not.toHaveBeenCalled();
    expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    expect(fetchResumeVersionsApi).not.toHaveBeenCalled();
    flush.resolve();
    await vi.waitFor(() =>
      expect(fetchWorkspaceRouteData).toHaveBeenCalledOnce(),
    );
    for (const fetch of [fetchResumeApi, fetchResumeVersionsApi])
      expect(fetch).toHaveBeenCalledExactlyOnceWith("resume-a", {
        signal,
        notifyOnError: false,
      });
    expect(fetchWorkspaceRouteData).toHaveBeenCalledExactlyOnceWith(
      "resume-detail",
      { signal, notifyOnError: false },
    );
    const data = {
      defaultTemplateIds: { en: "minimal", zh: "minimal" },
      customTemplates: [],
      modelConfigs: [],
      agentSettings: normalizeAgentSettings(null),
      theme: "dark",
    } as const;
    const saved = {
      resume: createResumeDetailItem(),
      savedAt: "now",
      versionId: "v1",
    };
    const history = [{ versionId: "v1", savedAt: "now" }];
    const rejected =
      outcome === "aborted"
        ? expect(result).rejects.toMatchObject({ name: "AbortError" })
        : null;
    const payload = { ...data, customTemplates: [], modelConfigs: [] };
    route.resolve({ kind: "resume-detail", data: payload });
    detail.resolve(saved);
    if (outcome === "success") versions.resolve({ versions: history });
    else
      versions.reject(
        outcome === "aborted"
          ? new DOMException("Cancelled", "AbortError")
          : new Error("History unavailable"),
      );
    if (rejected) await rejected;
    else {
      const loaded = await result;
      expect(loaded).toEqual({
        detail: saved,
        routeData: payload,
        versions: outcome === "success" ? history : [],
      });
      expect(loaded.detail).toBe(saved);
      expect(loaded.routeData).toBe(payload);
    }
    expect(accept.mock.lastCall?.[0]).toBe(payload);
  },
);

const routeData = {
  defaultTemplateIds: { en: "minimal", zh: "minimal" },
  customTemplates: [],
  resumes: [],
  deletedResumes: [],
  deletedTemplates: [],
  modelConfigs: [],
  agentSettings: normalizeAgentSettings(null),
};
function preferences() {
  return {
    flush: vi.fn(async () => {}),
    prepareRead: vi.fn(async () => vi.fn()),
  } as unknown as WorkspacePreferencesPersistence;
}

it.each([
  ["resume", "resume-gallery"],
  ["templates", "template-gallery"],
  ["trash", "trash"],
  ["models", "models"],
  ["settings", "settings"],
] as const)(
  "prepares %s with modules in parallel and route data after pending preference writes",
  async (view, kind) => {
    const persistence = preferences();
    const flushed = Promise.withResolvers<void>();
    vi.mocked(persistence.flush).mockReturnValue(flushed.promise);
    vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
      kind,
      data: routeData,
    });
    const signal = new AbortController().signal;
    const pending = prepareWorkspaceRoute(view, persistence, { signal });
    expect(preloadWorkspaceRoute).toHaveBeenCalledExactlyOnceWith(view);
    expect(fetchWorkspaceRouteData).not.toHaveBeenCalled();
    flushed.resolve();
    expect(await pending).toEqual({ view, data: routeData });
    expect(fetchWorkspaceRouteData).toHaveBeenCalledExactlyOnceWith(kind, {
      signal,
      notifyOnError: false,
    });
  },
);

it("prepares a newly saved resume from its creation receipt without redundant detail or history reads", async () => {
  const detail = {
    resume: createResumeDetailItem(),
    savedAt: "now",
    versionId: "v1",
  };
  vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
    kind: "resume-detail",
    data: routeData,
  });
  const pending = prepareCreatedResumeDetailRoute(detail, preferences(), {
    signal: new AbortController().signal,
  });
  expect(loadWorkspacePreferencesProvider).toHaveBeenCalledOnce();
  expect(loadResumeDetailWorkspacePage).toHaveBeenCalledOnce();
  expect(loadDocumentCanvas).toHaveBeenCalledOnce();
  expect(await pending).toEqual({
    detail,
    routeData,
    versions: [{ savedAt: "now", versionId: "v1" }],
  });
  expect(fetchResumeApi).not.toHaveBeenCalled();
  expect(fetchResumeVersionsApi).not.toHaveBeenCalled();
});

it("preloads existing resume detail and shares the same complete route read", async () => {
  const detail = {
    resume: createResumeDetailItem(),
    savedAt: "now",
    versionId: "v1",
  };
  vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
    kind: "resume-detail",
    data: routeData,
  });
  vi.mocked(fetchResumeApi).mockResolvedValue(detail);
  vi.mocked(fetchResumeVersionsApi).mockResolvedValue({ versions: [] });
  const pending = prepareResumeDetailRoute(detail.resume.id, preferences(), {
    signal: new AbortController().signal,
  });
  expect(loadResumeDetailWorkspacePage).toHaveBeenCalledOnce();
  expect(loadDocumentCanvas).toHaveBeenCalledOnce();
  expect(await pending).toEqual({ detail, routeData, versions: [] });
});

it.each(["minimal", "custom-a"])(
  "prepares template %s and replaces only the requested custom detail with its fresh checkpoint",
  async (id) => {
    const original = createResumeDetailTemplate("custom-a");
    const other = createResumeDetailTemplate("custom-b");
    const template = { ...original, name: "Fresh server name" };
    const checkpoint = { ...template, name: "Checkpoint name" };
    const data = { ...routeData, customTemplates: [original, other] };
    vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
      kind: "template-detail",
      data,
    });
    vi.mocked(fetchTemplateApi).mockResolvedValue({ template, checkpoint });
    const signal = new AbortController().signal;
    const result = await prepareTemplateDetailRoute(id, preferences(), {
      signal,
    });
    expect(loadWorkspacePreferencesProvider).toHaveBeenCalledOnce();
    expect(loadTemplateDetailWorkspacePage).toHaveBeenCalledOnce();
    expect(loadDocumentCanvas).toHaveBeenCalledOnce();
    expect(fetchWorkspaceRouteData).toHaveBeenCalledExactlyOnceWith(
      "template-detail",
      { signal, notifyOnError: false },
    );
    if (id === "minimal") {
      expect(fetchTemplateApi).not.toHaveBeenCalled();
      expect(result).toEqual({ ...data, checkpoint: null });
    } else {
      expect(fetchTemplateApi).toHaveBeenCalledExactlyOnceWith(id, {
        signal,
        notifyOnError: false,
      });
      expect(result).toEqual({
        ...data,
        customTemplates: [template, other],
        checkpoint,
      });
    }
  },
);

it("rejects failed target-template reads without exposing stale catalog data", async () => {
  const error = new Error("Template removed");
  vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
    kind: "template-detail",
    data: routeData,
  });
  vi.mocked(fetchTemplateApi).mockRejectedValue(error);
  await expect(
    loadTemplateDetailRouteData("custom-a", preferences(), {
      signal: new AbortController().signal,
    }),
  ).rejects.toBe(error);
});
