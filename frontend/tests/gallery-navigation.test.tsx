import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useResumeGalleryWorkspace } from "@/components/workspace/use-resume-gallery-workspace";
import { useTemplateGalleryWorkspace } from "@/components/workspace/use-template-gallery-workspace";
import {
  prepareResumeDetailRoute,
  prepareCreatedResumeDetailRoute,
  prepareTemplateDetailRoute,
  preloadResumeDetailRoute,
  preloadTemplateDetailRoute,
} from "@/components/workspace/workspace-route-preparation";
import { showWorkspaceNavigationError } from "@/components/workspace/workspace-navigation-notifications";
import { createResumeApi, createTemplateApi } from "@/lib/workspace-api";
import { importResumePayload, importTemplatePayload } from "@/lib/import-api";
import {
  clearWorkspaceRouteMemory,
  createWorkspaceLateralRouteHandoff,
} from "@/lib/workspace-route-memory";
import {
  getResumeDetailRouteHandoff,
  getTemplateDetailRouteHandoff,
} from "@/lib/workspace-detail-route-handoff";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import type {
  PreparedResumeDetailRouteData,
  PreparedTemplateDetailRouteData,
} from "@/lib/workspace-route-data";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";

vi.mock("@/components/workspace/workspace-route-preparation", () => ({
  prepareResumeDetailRoute: vi.fn(),
  prepareCreatedResumeDetailRoute: vi.fn(),
  prepareTemplateDetailRoute: vi.fn(),
  preloadResumeDetailRoute: vi.fn(),
  preloadTemplateDetailRoute: vi.fn(),
  fetchWorkspacePageData: vi.fn(),
}));
vi.mock("@/lib/workspace-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/workspace-api")>()),
  createResumeApi: vi.fn(),
  createTemplateApi: vi.fn(),
}));
vi.mock("@/components/workspace/workspace-navigation-notifications", () => ({
  showWorkspaceNavigationError: vi.fn(),
  clearWorkspaceNavigationError: vi.fn(),
}));
vi.mock("@/lib/import-api", () => ({
  importResumePayload: vi.fn(),
  importTemplatePayload: vi.fn(),
}));

const resumes = [
  createResumeDetailItem(),
  createResumeDetailItem({ id: "resume-b" }),
];
const templates = [
  createResumeDetailTemplate("custom-a"),
  createResumeDetailTemplate("custom-b"),
];
const data = {
  resumes,
  customTemplates: templates,
  defaultTemplateIds: { en: "minimal", zh: "minimal" },
  modelConfigs: [],
  agentSettings: normalizeAgentSettings(null),
};
const resumeData = (id: string): PreparedResumeDetailRouteData => ({
  detail: {
    resume: createResumeDetailItem({ id }),
    savedAt: "now",
    versionId: "v1",
  },
  routeData: data,
  versions: [],
});
const templateData: PreparedTemplateDetailRouteData = {
  ...data,
  checkpoint: templates[0],
};
beforeEach(() => {
  vi.resetAllMocks();
  clearWorkspaceRouteMemory();
  vi.mocked(preloadResumeDetailRoute).mockResolvedValue(
    [] as unknown as Awaited<ReturnType<typeof preloadResumeDetailRoute>>,
  );
  vi.mocked(preloadTemplateDetailRoute).mockResolvedValue(
    [] as unknown as Awaited<ReturnType<typeof preloadTemplateDetailRoute>>,
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

function mountResume() {
  const fixture = createWorkspaceFixture({
    path: "/resume",
    state: createWorkspaceLateralRouteHandoff({ view: "resume", data }),
  });
  const hook = renderHook(
    () =>
      useResumeGalleryWorkspace({
        locale: "en",
        messages: fixture.preferences.messages,
      }),
    { wrapper: fixture.wrapper },
  );
  return { fixture, ...hook };
}
function mountTemplate() {
  const fixture = createWorkspaceFixture({
    path: "/templates",
    state: createWorkspaceLateralRouteHandoff({ view: "templates", data }),
  });
  const hook = renderHook(
    () =>
      useTemplateGalleryWorkspace({
        locale: "en",
        messages: fixture.preferences.messages,
      }),
    { wrapper: fixture.wrapper },
  );
  return { fixture, ...hook };
}

describe("resume gallery navigation", () => {
  it("publishes every imported receipt once and navigates with the first complete detail and new gallery count", async () => {
    const view = mountResume();
    const first = resumeData("resume-c");
    const second = resumeData("resume-d");
    vi.mocked(importResumePayload).mockResolvedValue({
      resumes: [first.detail.resume, second.detail.resume].map((item) => ({
        ...item,
        template: "minimal" as const,
      })),
      templates: [],
    });
    vi.mocked(createResumeApi)
      .mockResolvedValueOnce(first.detail)
      .mockResolvedValueOnce(second.detail);
    const gate = Promise.withResolvers<PreparedResumeDetailRouteData>();
    vi.mocked(prepareCreatedResumeDetailRoute).mockReturnValue(gate.promise);
    const file = new File(["{}"], "resumes.json", { type: "application/json" });
    let importing!: Promise<void>;
    await act(async () => {
      importing = view.result.current.importResume(file);
      await vi.waitFor(() =>
        expect(prepareCreatedResumeDetailRoute).toHaveBeenCalledOnce(),
      );
    });
    await act(() => view.result.current.importResume(file));
    expect(createResumeApi).toHaveBeenCalledTimes(2);
    expect(view.result.current.resumes.map(({ id }) => id)).toEqual([
      "resume-a",
      "resume-b",
      "resume-c",
      "resume-d",
    ]);
    expect(view.fixture.router.state.location.pathname).toBe("/resume");
    expect(vi.mocked(prepareCreatedResumeDetailRoute).mock.calls[0][0]).toEqual(
      first.detail,
    );
    await act(async () => {
      gate.resolve(first);
      await importing;
    });
    expect(view.result.current.isImporting).toBe(false);
    expect(
      getResumeDetailRouteHandoff(
        view.fixture.router.state.location.state,
        "resume-c",
      ),
    ).toMatchObject({ payload: first, resumeOrdinal: 3, resumeCount: 4 });
  });
  it("warms modules without reading detail and waits for a complete target before committing its ordinal", async () => {
    const view = mountResume();
    act(view.result.current.preloadResumeDetail);
    expect(preloadResumeDetailRoute).toHaveBeenCalledOnce();
    expect(prepareResumeDetailRoute).not.toHaveBeenCalled();
    await act(() => view.result.current.openResume("missing"));
    expect(prepareResumeDetailRoute).not.toHaveBeenCalled();
    const gate = Promise.withResolvers<PreparedResumeDetailRouteData>();
    vi.mocked(prepareResumeDetailRoute).mockReturnValue(gate.promise);
    let opening!: Promise<void>;
    act(() => {
      opening = view.result.current.openResume("resume-b");
    });
    expect(view.result.current.openingResumeId).toBe("resume-b");
    expect(view.fixture.router.state.location.pathname).toBe("/resume");
    const prepared = resumeData("resume-b");
    await act(async () => {
      gate.resolve(prepared);
      await opening;
    });
    expect(view.fixture.router.state.location.pathname).toBe(
      "/resume/resume-b",
    );
    expect(
      getResumeDetailRouteHandoff(
        view.fixture.router.state.location.state,
        "resume-b",
      ),
    ).toMatchObject({ payload: prepared, resumeOrdinal: 2, resumeCount: 2 });
  });
  it.each(["success", "failure"])(
    "rejects an obsolete target's late %s and keeps the newer card pending",
    async (outcome) => {
      const view = mountResume();
      const old = Promise.withResolvers<PreparedResumeDetailRouteData>();
      const current = Promise.withResolvers<PreparedResumeDetailRouteData>();
      vi.mocked(prepareResumeDetailRoute)
        .mockReturnValueOnce(old.promise)
        .mockReturnValueOnce(current.promise);
      let first!: Promise<void>, second!: Promise<void>;
      act(() => {
        first = view.result.current.openResume("resume-a");
      });
      const oldSignal = vi.mocked(prepareResumeDetailRoute).mock.calls[0][2]
        .signal;
      act(() => {
        second = view.result.current.openResume("resume-b");
      });
      expect(oldSignal.aborted).toBe(true);
      await act(async () => {
        if (outcome === "success") old.resolve(resumeData("resume-a"));
        else old.reject(new Error("Stale target"));
        await first;
      });
      expect(view.fixture.router.state.location.pathname).toBe("/resume");
      expect(view.result.current.openingResumeId).toBe("resume-b");
      expect(showWorkspaceNavigationError).not.toHaveBeenCalled();
      await act(async () => {
        current.resolve(resumeData("resume-b"));
        await second;
      });
      expect(view.fixture.router.state.location.pathname).toBe(
        "/resume/resume-b",
      );
    },
  );
  it("keeps the gallery interactive after target preparation fails", async () => {
    const view = mountResume();
    vi.mocked(prepareResumeDetailRoute).mockRejectedValue(
      new Error("Deleted target"),
    );
    await act(() => view.result.current.openResume("resume-a"));
    expect(view.fixture.router.state.location.pathname).toBe("/resume");
    expect(view.result.current.openingResumeId).toBeNull();
    expect(view.result.current.resumes).toEqual(resumes);
    expect(showWorkspaceNavigationError).toHaveBeenCalledExactlyOnceWith(
      view.fixture.preferences.messages.loadError,
    );
  });
  it.each(["success", "failure", "superseded"])(
    "preserves a created resume when route preparation is %s without duplicate creation",
    async (outcome) => {
      const view = mountResume();
      const created = resumeData("resume-c");
      const gate = Promise.withResolvers<PreparedResumeDetailRouteData>();
      vi.mocked(createResumeApi).mockResolvedValue(created.detail);
      vi.mocked(prepareCreatedResumeDetailRoute).mockReturnValue(gate.promise);
      let creation!: Promise<void>;
      await act(async () => {
        creation = view.result.current.createResume("en", "minimal");
        await view.result.current.createResume("en", "minimal");
      });
      expect(createResumeApi).toHaveBeenCalledOnce();
      expect(view.result.current.resumes).toHaveLength(2);
      if (outcome === "superseded") {
        vi.mocked(prepareResumeDetailRoute).mockResolvedValue(
          resumeData("resume-b"),
        );
        await act(() => view.result.current.openResume("resume-b"));
      }
      await act(async () => {
        if (outcome === "failure") gate.reject(new Error("Chunk unavailable"));
        else if (outcome === "superseded")
          gate.reject(new DOMException("Cancelled", "AbortError"));
        else gate.resolve(created);
        await creation;
      });
      expect(view.result.current.resumes.map(({ id }) => id)).toEqual([
        "resume-a",
        "resume-b",
        "resume-c",
      ]);
      expect(view.result.current.isCreating).toBe(false);
      if (outcome === "success") {
        expect(view.fixture.router.state.location.pathname).toBe(
          "/resume/resume-c",
        );
        expect(
          getResumeDetailRouteHandoff(
            view.fixture.router.state.location.state,
            "resume-c",
          ),
        ).toMatchObject({ resumeOrdinal: 3, resumeCount: 3, payload: created });
      } else
        expect(view.fixture.router.state.location.pathname).toBe(
          outcome === "superseded" ? "/resume/resume-b" : "/resume",
        );
      if (outcome === "failure")
        expect(showWorkspaceNavigationError).toHaveBeenCalledExactlyOnceWith(
          view.fixture.preferences.messages.resumeCreatedOpenFailed,
        );
    },
  );
});

describe("template gallery navigation", () => {
  it("imports all templates and navigates with a fresh catalog containing every persisted receipt", async () => {
    const view = mountTemplate();
    const imported = [
      createResumeDetailTemplate("custom-c"),
      createResumeDetailTemplate("custom-d"),
    ];
    vi.mocked(importTemplatePayload).mockResolvedValue({ templates: imported });
    vi.mocked(createTemplateApi)
      .mockResolvedValueOnce({ template: imported[0] })
      .mockResolvedValueOnce({ template: imported[1] });
    await act(() =>
      view.result.current.importTemplates(
        new File(["{}"], "templates.json", { type: "application/json" }),
      ),
    );
    expect(createTemplateApi).toHaveBeenCalledTimes(2);
    expect(view.fixture.router.state.location.pathname).toBe(
      "/template/custom-c",
    );
    expect(
      getTemplateDetailRouteHandoff(
        view.fixture.router.state.location.state,
        "custom-c",
      )?.data.customTemplates,
    ).toEqual([...templates, ...imported]);
    expect(view.result.current.isImporting).toBe(false);
  });
  it("warms only detail modules and hands a fully prepared template and its selected language to the route", async () => {
    const view = mountTemplate();
    act(view.result.current.preloadTemplateDetail);
    expect(preloadTemplateDetailRoute).toHaveBeenCalledOnce();
    expect(prepareTemplateDetailRoute).not.toHaveBeenCalled();
    await act(() => view.result.current.openTemplate("missing"));
    expect(prepareTemplateDetailRoute).not.toHaveBeenCalled();
    act(() => view.result.current.setTemplateLocale("zh"));
    const gate = Promise.withResolvers<PreparedTemplateDetailRouteData>();
    vi.mocked(prepareTemplateDetailRoute).mockReturnValue(gate.promise);
    let opening!: Promise<void>;
    act(() => {
      opening = view.result.current.openTemplate("custom-a");
    });
    expect(view.result.current.openingTemplateId).toBe("custom-a");
    expect(view.fixture.router.state.location.pathname).toBe("/templates");
    await act(async () => {
      gate.resolve(templateData);
      await opening;
    });
    expect(view.fixture.router.state.location.pathname).toBe(
      "/template/custom-a",
    );
    expect(
      getTemplateDetailRouteHandoff(
        view.fixture.router.state.location.state,
        "custom-a",
      ),
    ).toMatchObject({ data: templateData, templateLocale: "zh" });
  });
  it.each(["success", "failure"])(
    "does not let an old template's %s clear the active target or navigate",
    async (outcome) => {
      const view = mountTemplate();
      const old = Promise.withResolvers<PreparedTemplateDetailRouteData>();
      const current = Promise.withResolvers<PreparedTemplateDetailRouteData>();
      vi.mocked(prepareTemplateDetailRoute)
        .mockReturnValueOnce(old.promise)
        .mockReturnValueOnce(current.promise);
      let first!: Promise<void>, second!: Promise<void>;
      act(() => {
        first = view.result.current.openTemplate("custom-a");
      });
      const signal = vi.mocked(prepareTemplateDetailRoute).mock.calls[0][2]
        .signal;
      act(() => {
        second = view.result.current.openTemplate("custom-b");
      });
      expect(signal.aborted).toBe(true);
      await act(async () => {
        if (outcome === "success") old.resolve(templateData);
        else old.reject(new Error("Old target failed"));
        await first;
      });
      expect(view.result.current.openingTemplateId).toBe("custom-b");
      expect(view.fixture.router.state.location.pathname).toBe("/templates");
      expect(showWorkspaceNavigationError).not.toHaveBeenCalled();
      await act(async () => {
        current.resolve(templateData);
        await second;
      });
      expect(view.fixture.router.state.location.pathname).toBe(
        "/template/custom-b",
      );
    },
  );
  it("stays in the gallery when the fresh template is unavailable", async () => {
    const view = mountTemplate();
    vi.mocked(prepareTemplateDetailRoute).mockRejectedValue(
      new Error("Template deleted"),
    );
    await act(() => view.result.current.openTemplate("custom-a"));
    expect(view.fixture.router.state.location.pathname).toBe("/templates");
    expect(view.result.current.openingTemplateId).toBeNull();
    expect(showWorkspaceNavigationError).toHaveBeenCalledExactlyOnceWith(
      view.fixture.preferences.messages.loadError,
    );
  });
  it.each(["success", "failure", "superseded"])(
    "publishes a created template after %s while waiting for its module",
    async (outcome) => {
      const view = mountTemplate();
      const created = createResumeDetailTemplate("custom-c");
      const module =
        Promise.withResolvers<
          Awaited<ReturnType<typeof preloadTemplateDetailRoute>>
        >();
      vi.mocked(preloadTemplateDetailRoute).mockReturnValue(module.promise);
      vi.mocked(createTemplateApi).mockResolvedValue({ template: created });
      let creation!: Promise<void>;
      await act(async () => {
        creation = view.result.current.createCustomTemplate();
        await view.result.current.createCustomTemplate();
      });
      expect(createTemplateApi).toHaveBeenCalledOnce();
      expect(view.result.current.routeData.customTemplates).toHaveLength(2);
      if (outcome === "superseded") {
        vi.mocked(prepareTemplateDetailRoute).mockResolvedValue(templateData);
        await act(() => view.result.current.openTemplate("custom-b"));
      }
      await act(async () => {
        if (outcome === "failure" || outcome === "superseded")
          module.reject(new Error("Chunk unavailable"));
        else
          module.resolve(
            [] as unknown as Awaited<
              ReturnType<typeof preloadTemplateDetailRoute>
            >,
          );
        await creation;
      });
      expect(view.result.current.isCreating).toBe(false);
      expect(
        view.result.current.routeData.customTemplates.map(({ id }) => id),
      ).toEqual(["custom-a", "custom-b", "custom-c"]);
      if (outcome === "success") {
        expect(view.fixture.router.state.location.pathname).toBe(
          "/template/custom-c",
        );
        expect(
          getTemplateDetailRouteHandoff(
            view.fixture.router.state.location.state,
            "custom-c",
          )?.data.customTemplates,
        ).toContainEqual(created);
      } else
        expect(view.fixture.router.state.location.pathname).toBe(
          outcome === "superseded" ? "/template/custom-b" : "/templates",
        );
      if (outcome === "failure")
        expect(showWorkspaceNavigationError).toHaveBeenCalledExactlyOnceWith(
          view.fixture.preferences.messages.templateCreatedOpenFailed,
        );
    },
  );
});
