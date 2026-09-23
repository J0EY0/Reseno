import { act, render, waitFor } from "@testing-library/react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ResumeDetailWorkspacePage } from "@/components/workspace/resume-detail-workspace-page";
import { TemplateDetailWorkspacePage } from "@/components/workspace/template-detail-workspace-page";
import { WorkspacePreferencesContext } from "@/components/workspace/workspace-preferences-context";
import {
  createWorkspaceHandoffToken,
  readWorkspaceHandoffToken,
} from "@/lib/workspace-route-handoff";
import { createWorkspaceFixture } from "./helpers/workspace-fixtures";

const hooks = vi.hoisted(() => ({ resume: vi.fn(), template: vi.fn() }));
vi.mock("@/components/workspace/use-resume-detail-workspace", () => ({
  useResumeDetailWorkspace: hooks.resume,
}));
vi.mock("@/components/workspace/use-template-detail-workspace", () => ({
  useTemplateDetailWorkspace: hooks.template,
}));
vi.mock("@/components/workspace/resume-detail-workspace-view", () => ({
  ResumeDetailWorkspaceView: () => (
    <main id="main-content" tabIndex={-1}>
      Resume editor
    </main>
  ),
}));
vi.mock("@/components/workspace/template-detail-workspace-view", () => ({
  TemplateDetailWorkspaceView: () => (
    <main id="main-content" tabIndex={-1}>
      Template editor
    </main>
  ),
}));

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.stubGlobal("scrollTo", vi.fn());
  hooks.resume.mockReturnValue({
    model: { commands: { saveAndReload: vi.fn() } },
    previewRef: { current: null },
  });
  hooks.template.mockReturnValue({ saveAndReload: vi.fn() });
});
afterEach(() => vi.unstubAllGlobals());

it.each(["resume", "template"] as const)(
  "consumes %s handoff once, remounts for a new id and focuses only on PUSH",
  async (kind) => {
    const hook = hooks[kind];
    const { preferences } = createWorkspaceFixture();
    const router = createBrowserRouter([
      { path: "/", element: <div>Home</div> },
      {
        path: "/resume/:id",
        element: <ResumeDetailWorkspacePage onLogout={vi.fn()} />,
      },
      {
        path: "/template/:id",
        element: <TemplateDetailWorkspacePage onLogout={vi.fn()} />,
      },
    ]);
    const view = render(
      <WorkspacePreferencesContext value={preferences}>
        <RouterProvider router={router} />
      </WorkspacePreferencesContext>,
    );
    const first = {
      kind: `${kind}-detail-handoff`,
      token: createWorkspaceHandoffToken({ seed: "first" }),
    };
    try {
      await act(() => router.navigate(`/${kind}/a`, { state: first }));
      expect(hook.mock.lastCall?.[0].routeState).toEqual(first);
      expect(readWorkspaceHandoffToken(first.token)).toBeUndefined();
      expect(window.history.state.usr).toBeNull();
      expect(document.activeElement).toBe(view.getByRole("main"));
      expect(window.scrollTo).toHaveBeenCalledExactlyOnceWith({
        left: 0,
        top: 0,
        behavior: "auto",
      });
      await act(() =>
        router.navigate(`/${kind}/a`, { replace: true, state: null }),
      );
      expect(hook.mock.lastCall?.[0].routeState).toEqual(first);
      expect(window.scrollTo).toHaveBeenCalledOnce();
      const second = {
        kind: `${kind}-detail-handoff`,
        token: createWorkspaceHandoffToken({ seed: "second" }),
      };
      await act(() => router.navigate(`/${kind}/b`, { state: second }));
      expect(hook.mock.lastCall?.[0].routeState).toEqual(second);
      expect(hook.mock.lastCall?.[0][`${kind}Id`]).toBe("b");
      expect(readWorkspaceHandoffToken(second.token)).toBeUndefined();
      expect(window.scrollTo).toHaveBeenCalledTimes(2);
      await act(() => router.navigate(-1));
      await waitFor(() =>
        expect(hook.mock.lastCall?.[0][`${kind}Id`]).toBe("a"),
      );
      expect(hook.mock.lastCall?.[0].routeState).toBeNull();
      expect(window.scrollTo).toHaveBeenCalledTimes(2);
    } finally {
      router.dispose();
    }
  },
);
