import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import expect

from tests.e2e.test_oauth_login import LoginFlow
from tests.e2e.test_oauth_login import login_flow as login_flow

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
@pytest.mark.parametrize("workspace_delay_ms", [0, 300])
def test_github_login_callback_stays_pending_until_workspace_is_ready(
    login_flow: Callable[..., LoginFlow],
    tmp_path: Path,
    workspace_delay_ms: int,
) -> None:
    flow = login_flow()
    flow.hold_gallery = bool(workspace_delay_ms)
    frames: list[dict[str, Any]] = []
    prefix = "__OAUTH_LOGIN_RETURN_FRAME__"
    flow.context.add_init_script("""(() => {
      const callback = location.pathname === '/login'
        && new URLSearchParams(location.hash.slice(1)).has('oauth_code');
      if (!callback) return;
      function visible(element) {
        if (!element?.getBoundingClientRect().height) return false;
        for (let node = element; node; node = node.parentElement) {
          const css = getComputedStyle(node);
          if (css.display === 'none' || css.visibility === 'hidden'
            || Number(css.opacity) === 0) return false;
        }
        return true;
      }
      function sample() {
        const spinner = document.querySelector(
          'svg[role="status"][aria-label="Loading"]');
        const frame = {
          time: performance.now(), path: location.pathname,
          login: visible(document.querySelector('#username')),
          busy: document.querySelector('[aria-label="Continue with GitHub"]')
            ?.getAttribute('aria-busy') === 'true',
          dialog: visible(document.querySelector('[role="dialog"]')),
          card: visible(document.querySelector('[data-slot="card"]')),
          spinner: visible(spinner)
            && spinner.parentElement.getBoundingClientRect().height >= innerHeight - 1,
          workspace: visible(document.querySelector(
            '[data-slot="sidebar-inset"] input[name="resume-search"]')),
          workspaceShell: visible(document.querySelector(
            '[data-slot="sidebar-inset"]')),
          skeleton: Boolean(document.querySelector(
            '[data-slot="workspace-entry-skeleton"]')),
        };
        window.__oauthReturnObserved ??= {};
        window.__oauthReturnObserved.spinner ||= frame.spinner;
        window.__oauthReturnObserved.workspace ||= frame.workspace;
        console.debug('__OAUTH_LOGIN_RETURN_FRAME__' + JSON.stringify(frame));
        requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    })();""")
    flow.page.on(
        "console",
        lambda message: (
            frames.append(json.loads(message.text.removeprefix(prefix)))
            if message.text.startswith(prefix)
            else None
        ),
    )
    flow.open()
    flow.start()
    flow.confirm()
    flow.page.wait_for_function("() => window.__oauthReturnObserved?.spinner")
    flow.finish()
    if workspace_delay_ms:
        flow.wait_count(flow.galleries, 1)
        flow.page.wait_for_timeout(workspace_delay_ms)
        expect(flow.page.locator('input[name="resume-search"]')).to_have_count(0)
        flow.respond(flow.galleries[0], flow.gallery_data())
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    expect(flow.page.get_by_role("dialog")).to_have_count(0)
    flow.page.wait_for_function("() => window.__oauthReturnObserved?.workspace")
    flow.assert_single_page()
    evidence = tmp_path / "oauth-current-page-return-frames.json"
    evidence.write_text(json.dumps(frames, ensure_ascii=False, indent=2))
    unwanted_content = [
        frame for frame in frames if frame["login"] or frame["card"] or frame["dialog"]
    ]
    invalid_workspace = [
        frame
        for frame in frames
        if frame["skeleton"] or (frame["workspaceShell"] and not frame["workspace"])
    ]
    first_spinner = next(
        index for index, frame in enumerate(frames) if frame["spinner"]
    )
    pending_frames = [
        frame for frame in frames[first_spinner:] if not frame["workspace"]
    ]
    blank_pending_frames = [frame for frame in pending_frames if not frame["spinner"]]
    assert any(frame["workspace"] for frame in frames)
    assert (
        not unwanted_content and not invalid_workspace and not blank_pending_frames
    ), {
        "unwantedContent": unwanted_content[:3],
        "invalidWorkspace": invalid_workspace[:3],
        "blankPendingFrames": blank_pending_frames[:3],
        "evidence": str(evidence),
    }
