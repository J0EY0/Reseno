"""Workspace navigation preserves readable content throughout its entry motion."""

from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Browser, Page

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _install_motion_recorder(page: Page) -> None:
    page.evaluate("""() => {
      window.routeMotion = { frames: [], starts: [], recording: false };
      document.addEventListener('animationstart', (event) => {
        if (window.routeMotion.recording &&
            event.target.matches('.workspace-route-stage')) {
          window.routeMotion.starts.push({
            view: event.target.dataset.workspaceView,
            name: event.animationName,
          });
        }
      });
      const sample = () => {
        const stage = document.querySelector('.workspace-route-stage');
        if (stage && window.routeMotion.recording) {
          const style = getComputedStyle(stage);
          let opacity = 1;
          for (let node = stage; node; node = node.parentElement) {
            opacity *= Number(getComputedStyle(node).opacity);
          }
          window.routeMotion.frames.push({
            view: stage.dataset.workspaceView,
            opacity,
            y: style.transform === 'none'
              ? 0 : new DOMMatrixReadOnly(style.transform).m42,
            running: stage.getAnimations().some(animation =>
              animation.playState === 'running' || animation.pending),
          });
        }
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    }""")


def _start_recording(page: Page) -> None:
    page.evaluate("""() => {
      window.routeMotion.frames = [];
      window.routeMotion.starts = [];
      window.routeMotion.recording = true;
    }""")


def _finish_recording(page: Page, view: str) -> dict[str, Any]:
    page.wait_for_function(
        """view => {
          const frames = window.routeMotion.frames.filter(f => f.view === view);
          return frames.length >= 2 && !frames.at(-1).running;
        }""",
        arg=view,
    )
    return page.evaluate("""() => {
      window.routeMotion.recording = false;
      return window.routeMotion;
    }""")


def _assert_entry_motion(
    recording: dict[str, Any], view: str, reduced_motion: str
) -> None:
    frames = [frame for frame in recording["frames"] if frame["view"] == view]
    starts = [start for start in recording["starts"] if start["view"] == view]
    assert len(frames) >= 2, recording
    opacities = [frame["opacity"] for frame in frames]
    assert min(opacities) >= 0.85, {"view": view, "opacities": opacities}
    assert frames[-1]["opacity"] == pytest.approx(1, abs=0.001), recording
    assert frames[-1]["y"] == pytest.approx(0, abs=0.05), recording
    if reduced_motion == "reduce":
        assert starts == [], recording
        assert all(abs(frame["y"]) < 0.05 for frame in frames), recording
    else:
        assert len(starts) == 1, recording
        assert starts[0]["name"] == "workspace-route-enter", recording
        assert any(frame["y"] > 0.1 for frame in frames), recording
        assert all(
            after["y"] <= before["y"] + 0.05
            for before, after in zip(frames, frames[1:], strict=False)
        ), recording


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_sidebar_navigation_preserves_content_during_entry_motion(
    browser: Browser,
    workspace_servers: tuple[str, str],
    theme: str,
    reduced_motion: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        color_scheme=theme,
        reduced_motion=reduced_motion,
        viewport={"width": 1672, "height": 900},
    )
    page = context.new_page()
    try:
        preferences = page.request.put(
            f"{frontend_url}/api/workspace/user-settings?locale=en",
            data={"settings": {"theme": theme}},
        )
        assert preferences.ok
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        assert page.locator("html").evaluate(
            "element => element.classList.contains('dark')"
        ) == (theme == "dark")
        _install_motion_recorder(page)
        for view, path in [
            ("settings", "/settings"),
            ("models", "/models"),
            ("templates", "/templates"),
            ("resume", "/resume"),
        ]:
            _start_recording(page)
            page.locator(f'a[href="{path}"]').click()
            page.wait_for_url(f"{frontend_url}{path}")
            recording = _finish_recording(page, view)
            _assert_entry_motion(recording, view, reduced_motion)

        page.evaluate("""() => {
          const fetch = window.fetch.bind(window);
          window.releaseObsoleteRoute = null;
          window.obsoleteRouteSettled = false;
          window.fetch = async (input, init) => {
            const request = new Request(input, init);
            const obsolete = new URL(request.url).pathname ===
              '/api/workspace/pages/trash';
            if (obsolete) {
              await new Promise(resolve => window.releaseObsoleteRoute = resolve);
              window.fetch = fetch;
            }
            try {
              return await fetch(input, init);
            } finally {
              if (obsolete) window.obsoleteRouteSettled = true;
            }
          };
        }""")
        _start_recording(page)
        page.locator('a[href="/trash"]').click()
        page.wait_for_function("window.releaseObsoleteRoute !== null")
        page.locator('a[href="/models"]').click()
        page.wait_for_url(f"{frontend_url}/models")
        recording = _finish_recording(page, "models")
        _assert_entry_motion(recording, "models", reduced_motion)
        page.evaluate("window.releaseObsoleteRoute()")
        page.wait_for_function("window.obsoleteRouteSettled")
        page.evaluate("""() => new Promise(resolve =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)))""")
        assert page.url == f"{frontend_url}/models"
        _start_recording(page)
        page.locator('a[href="/trash"]').click()
        page.wait_for_url(f"{frontend_url}/trash")
        recording = _finish_recording(page, "trash")
        _assert_entry_motion(recording, "trash", reduced_motion)
    finally:
        context.close()
