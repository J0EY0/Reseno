import type { WorkspaceView } from "@/types/resume";

const workspacePathByView: Record<WorkspaceView, string> = {
  resume: "/resume",
  templates: "/templates",
  trash: "/trash",
  models: "/models",
  settings: "/settings",
};

export function getWorkspacePath(view: WorkspaceView) {
  return workspacePathByView[view];
}
