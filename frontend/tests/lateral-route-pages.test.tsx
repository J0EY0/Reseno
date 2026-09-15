import { useLayoutEffect } from "react";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ResumeGalleryWorkspacePage } from "@/components/workspace/resume-gallery-workspace-page";
import { TemplateGalleryWorkspacePage } from "@/components/workspace/template-gallery-workspace-page";
import { TrashWorkspacePage } from "@/components/workspace/trash-workspace-page";
import { ModelsWorkspacePage } from "@/components/workspace/models-workspace-page";
import { SettingsWorkspacePage } from "@/components/workspace/settings-workspace-page";
import {
  useWorkspaceLateralRouteData,
  useRememberWorkspaceLateralRouteData,
} from "@/components/workspace/use-workspace-lateral-route-data";
import { fetchWorkspacePageData } from "@/components/workspace/workspace-route-preparation";
import {
  clearWorkspaceRouteMemory,
  createWorkspaceLateralRouteHandoff,
  resolveWorkspaceLateralRoute,
} from "@/lib/workspace-route-memory";
import { readWorkspaceHandoffToken } from "@/lib/workspace-route-handoff";
import type { WorkspaceView } from "@/types/resume";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";

vi.mock("@/components/workspace/workspace-route-preparation", () => ({
  fetchWorkspacePageData: vi.fn(),
}));
vi.mock("@/components/resume-gallery", () => ({
  ResumeGallery: () => <div>Resume content</div>,
}));
vi.mock("@/components/templates/template-gallery", () => ({
  TemplateGallery: () => <div>Template content</div>,
}));
vi.mock("@/components/recycle-bin-panel", () => ({
  RecycleBinPanel: () => <div>Trash content</div>,
}));
vi.mock("@/components/model-config-panel", () => ({
  ModelConfigPanel: () => <div>Model content</div>,
}));
vi.mock("@/components/settings-panel", () => ({
  SettingsPanel: () => <div>Settings content</div>,
}));
vi.mock("@/components/gallery-skeletons", () => ({
  GalleryRouteSkeleton: () => <div>Gallery skeleton</div>,
}));
vi.mock("@/lib/workspace-load-error", () => ({
  dismissWorkspaceLoadError: vi.fn(),
  showWorkspaceLoadError: vi.fn(),
}));
beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  clearWorkspaceRouteMemory();
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
const pages = {
  resume: ResumeGalleryWorkspacePage,
  templates: TemplateGalleryWorkspacePage,
  trash: TrashWorkspacePage,
  models: ModelsWorkspacePage,
  settings: SettingsWorkspacePage,
};
const kinds = {
  resume: "resume-gallery",
  templates: "template-gallery",
  trash: "trash",
  models: "models",
  settings: "settings",
} as const;
it.each(Object.keys(pages) as WorkspaceView[])(
  "publishes %s page data only after a usable load and keeps failures retryable",
  async (view) => {
    const fixture = createWorkspaceFixture({ path: `/${view}` });
    const data = {
      resumes: [],
      customTemplates: [],
      defaultTemplateIds: { en: "minimal", zh: "minimal" },
      deletedResumes: [],
      deletedTemplates: [],
      modelConfigs: [],
      agentSettings: fixture.preferences.agentSettings!,
    };
    const first =
      Promise.withResolvers<
        Awaited<ReturnType<typeof fetchWorkspacePageData>>
      >();
    vi.mocked(fetchWorkspacePageData).mockReturnValue(first.promise);
    const Page = pages[view];
    render(<Page onLogout={vi.fn()} />, { wrapper: fixture.wrapper });
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(resolveWorkspaceLateralRoute(null, view).data).toBeNull();
    if (view === "resume" || view === "templates")
      expect(screen.getByText("Gallery skeleton")).toBeTruthy();
    await act(async () => first.reject(new Error("Unavailable")));
    expect(resolveWorkspaceLateralRoute(null, view).data).toBeNull();
    expect(
      screen.getByText(fixture.preferences.messages.contentNotLoaded),
    ).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    vi.mocked(fetchWorkspacePageData).mockResolvedValue({
      kind: kinds[view],
      data,
    });
    fireEvent.click(
      screen.getByRole("button", { name: fixture.preferences.messages.retry }),
    );
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(
      screen.queryByText(fixture.preferences.messages.contentNotLoaded),
    ).toBeNull();
    const keys =
      view === "models" || view === "settings"
        ? ["agentSettings", "modelConfigs"]
        : [
            "defaultTemplateIds",
            "customTemplates",
            ...(view === "resume"
              ? ["resumes"]
              : view === "trash"
                ? ["deletedResumes", "deletedTemplates"]
                : []),
          ];
    expect(resolveWorkspaceLateralRoute(null, view).data).toEqual({
      ...Object.fromEntries(
        keys.map((key) => [key, data[key as keyof typeof data]]),
      ),
      theme: "light",
    });
  },
);
it("freezes the first handoff through replacement, consumes its token before paint, and remembers only committed non-null data", async () => {
  vi.useRealTimers();
  const initial = {
    defaultTemplateIds: { en: "minimal", zh: "minimal" },
    customTemplates: [],
    resumes: [],
  };
  const state = createWorkspaceLateralRouteHandoff({
    view: "resume",
    data: initial,
  });
  window.history.replaceState(
    { usr: state, key: "lateral-handoff" },
    "",
    "/resume",
  );
  let observed: ReturnType<typeof useWorkspaceLateralRouteData<"resume">> =
    null;
  function Page() {
    const data = useWorkspaceLateralRouteData("resume");
    useLayoutEffect(() => {
      observed = data;
    }, [data]);
    return <div>Mounted</div>;
  }
  const router = createBrowserRouter([{ path: "*", element: <Page /> }]);
  try {
    render(<RouterProvider router={router} />);
    expect(observed).toBe(initial);
    expect(window.history.state.usr).toBeNull();
    expect(readWorkspaceHandoffToken(state.token)).toBeUndefined();
    await act(() => router.navigate("/resume?sort=date", { replace: true }));
    expect(observed).toBe(initial);
    clearWorkspaceRouteMemory();
    const remember = renderHook(
      ({ data }) => useRememberWorkspaceLateralRouteData("resume", data),
      { initialProps: { data: null as typeof initial | null } },
    );
    expect(resolveWorkspaceLateralRoute(null, "resume").data).toBeNull();
    remember.rerender({ data: initial });
    expect(resolveWorkspaceLateralRoute(null, "resume").data).toBe(initial);
    remember.rerender({ data: null });
    expect(resolveWorkspaceLateralRoute(null, "resume").data).toBe(initial);
  } finally {
    router.dispose();
    window.history.replaceState(null, "", "/");
  }
});
