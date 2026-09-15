// @vitest-environment node
import { expect, it, vi } from "vitest";

import {
  getWorkspaceRouteLoader,
  preloadWorkspaceRoute,
} from "@/components/workspace/workspace-route-loaders";
import { getWorkspaceRoute } from "@/lib/workspace-route";

vi.mock("@/lib/route-loader", () => ({
  createRouteLoader: (_load: unknown, name: string) => () =>
    Promise.resolve(name),
}));

it.each([
  ["/resume", "resume-gallery", "ResumeGalleryWorkspacePage"],
  ["/resume/resume-id", "resume-detail", "ResumeDetailWorkspacePage"],
  ["/templates", "template-gallery", "TemplateGalleryWorkspacePage"],
  ["/template/template-id", "template-detail", "TemplateDetailWorkspacePage"],
  ["/models", "models", "ModelsWorkspacePage"],
  ["/settings", "settings", "SettingsWorkspacePage"],
  ["/trash", "trash", "TrashWorkspacePage"],
])(
  "resolves and preloads %s with case and trailing-slash variations",
  async (pathname, kind, page) => {
    for (const path of [
      pathname,
      `${pathname}/`,
      `${pathname.toUpperCase()}/`,
    ]) {
      expect(getWorkspaceRoute(path).kind).toBe(kind);
      expect(await getWorkspaceRouteLoader(path)()).toBe(page);
    }
  },
);

it.each([
  "/missing",
  "/unknown",
  "/templates/example",
  "/login",
  "/setup",
  "/auth/callback",
  "/pdf-export",
])("preloads the gallery redirect destination for %s", async (pathname) => {
  expect(getWorkspaceRoute(pathname).kind).toBe("unknown");
  expect(await getWorkspaceRouteLoader(pathname)()).toBe(
    "ResumeGalleryWorkspacePage",
  );
});

it.each([
  ["resume", "ResumeGalleryWorkspacePage"],
  ["templates", "TemplateGalleryWorkspacePage"],
  ["models", "ModelsWorkspacePage"],
  ["settings", "SettingsWorkspacePage"],
  ["trash", "TrashWorkspacePage"],
] as const)(
  "prepares %s with the shared providers and canonical page",
  async (view, page) => {
    expect(await preloadWorkspaceRoute(view)).toEqual([
      "WorkspacePreferencesProvider",
      "WorkspaceLateralLayout",
      page,
    ]);
  },
);
