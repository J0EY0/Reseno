from __future__ import annotations

from playwright.sync_api import Page


def install_workspace_frame_recorder(page: Page) -> None:
    page.add_init_script(
        """
        (() => {
          window.__workspaceFrames = [];
          window.__recordWorkspaceFrames = false;
          const visibleElement = (selector) => {
            const element = document.querySelector(selector);
            if (!element) return null;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            if (
              style.display === "none" ||
              style.visibility === "hidden" ||
              Number(style.opacity) === 0 ||
              rect.width === 0 ||
              rect.height === 0
            ) {
              return null;
            }
            return { element, rect };
          };
          const capture = (now) => {
            if (window.__recordWorkspaceFrames) {
              const resumeGallery = visibleElement(
                'input[name="resume-search"]',
              );
              const login = visibleElement('#username');
              const appFallback = visibleElement(
                '#root .h-svh > svg[role="status"][aria-label="Loading"], ' +
                '#root .min-h-svh > svg[role="status"][aria-label="Loading"]',
              );
              const routeSkeleton = visibleElement(
                '#root [data-slot="gallery-route-skeleton"], ' +
                '#root [data-slot="workspace-route-skeleton"], ' +
                '#root [data-slot="model-config-panel-skeleton"], ' +
                '#root [data-slot="workspace-panel-skeleton"], ' +
                '#root [data-slot="workspace-preview-skeleton"]',
              );
              const sidebar = visibleElement('[data-slot="sidebar-container"]');
              const resumeDetail = visibleElement(
                ".resume-workspace .resume-preview-card article.resume-page",
              );
              const resumePreviewFrame = visibleElement(
                '.resume-workspace [data-slot="document-canvas-viewport"]',
              );
              const templateGallery = visibleElement(
                '[data-slot="sidebar-inset"] a[href="/template/minimal"]',
              );
              const templateDetail = visibleElement(
                ".template-workspace .resume-preview-card article.resume-page",
              );
              const trashContent = visibleElement(
                '[data-slot="sidebar-inset"] section [data-slot="tabs-trigger"]',
              );
              const modelsContent = visibleElement(
                '[data-slot="sidebar-inset"] [data-slot="empty-description"]',
              );
              const settingsContent = visibleElement(
                '[data-slot="sidebar-inset"] ' +
                '[data-slot="tabs-trigger"][data-state="active"]',
              );
              const resumePreviewFits = Boolean(
                resumeDetail &&
                resumePreviewFrame &&
                resumeDetail.rect.left >= resumePreviewFrame.rect.left - 1 &&
                resumeDetail.rect.right <= resumePreviewFrame.rect.right + 1
              );
              window.__workspaceFrames.push({
                time: now,
                path: window.location.pathname,
                hasResumeGallery: Boolean(resumeGallery),
                hasLogin: Boolean(login),
                hasAuthCard: Boolean(visibleElement(
                  '#root > main > [data-slot="card"]'
                )),
                hasAppFallback: Boolean(appFallback),
                hasEntrySkeleton: Boolean(visibleElement(
                  '[data-slot="workspace-entry-skeleton"]'
                )),
                hasRouteSkeleton: Boolean(routeSkeleton),
                hasSidebar: Boolean(sidebar),
                hasResumeDetail: Boolean(resumeDetail),
                resumePreviewFits,
                resumePreviewWidth: resumeDetail?.rect.width ?? null,
                hasTemplateGallery: Boolean(templateGallery),
                hasTemplateDetail: Boolean(templateDetail),
                hasTrashContent: Boolean(trashContent),
                hasModelsContent: Boolean(modelsContent),
                hasSettingsContent: Boolean(settingsContent),
              });
            }
            window.requestAnimationFrame(capture);
          };
          window.requestAnimationFrame(capture);
        })();
        """,
    )


def start_workspace_frame_recording(page: Page) -> None:
    page.evaluate(
        """
        () => {
          window.__workspaceFrames = [];
          window.__recordWorkspaceFrames = true;
        }
        """,
    )


def stop_workspace_frame_recording(page: Page) -> list[dict[str, object]]:
    return page.evaluate(
        """
        () => {
          window.__recordWorkspaceFrames = false;
          return window.__workspaceFrames;
        }
        """,
    )


def boolean_runs(values: list[bool]) -> list[tuple[bool, int]]:
    runs: list[tuple[bool, int]] = []

    for value in values:
        if runs and runs[-1][0] == value:
            previous_value, count = runs[-1]
            runs[-1] = previous_value, count + 1
        else:
            runs.append((value, 1))

    return runs


def assert_visible_once_mounted(
    frames: list[dict[str, object]],
    key: str,
) -> None:
    states = [bool(frame[key]) for frame in frames]

    assert any(states), boolean_runs(states)
    first_visible_frame = states.index(True)
    assert all(states[first_visible_frame:]), boolean_runs(states)
