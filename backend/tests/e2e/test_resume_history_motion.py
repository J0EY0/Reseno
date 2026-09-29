from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, Route, expect

from tests.e2e.browser_support import DeferredRoute, authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _record_history_motion(page: Page) -> None:
    page.evaluate(
        """() => {
          window.historyMotion = {recording: true, frames: []};
          const sample = () => {
            if (!window.historyMotion.recording) return;
            const viewport = document.querySelector(
              '[data-slot="document-canvas-viewport"]');
            const paper = document.querySelector('.resume-page');
            const popover = document.querySelector('[data-slot="popover-content"]');
            window.historyMotion.frames.push({
              viewportTop: viewport.getBoundingClientRect().top,
              paperTop: paper?.getBoundingClientRect().top,
              menuHeight: popover.getBoundingClientRect().height,
              rows: Array.from(popover?.querySelectorAll('button') ?? []).map(row => ({
                top: row.getBoundingClientRect().top, disabled: row.disabled,
              })),
              text: paper?.querySelector('h1')?.textContent ?? '',
            });
            requestAnimationFrame(sample);
          };
          sample();
        }"""
    )


def _finish_history_motion(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(
        """async () => {
          await new Promise(requestAnimationFrame);
          const card = document.querySelector('.resume-preview-card');
          await Promise.allSettled(card.getAnimations({subtree: true})
            .filter(animation => animation.effect.getTiming().iterations !== Infinity)
            .map(animation => animation.finished));
          await new Promise(requestAnimationFrame);
          window.historyMotion.recording = false;
          return window.historyMotion.frames;
        }"""
    )


def _fixed_saved_at(route: Route) -> None:
    response = route.fetch()
    payload = response.json()
    data = payload["data"]
    if "savedAt" in data:
        data["savedAt"] = "2026-09-29T03:34:13Z"
    for version in data.get("versions", []):
        version["savedAt"] = "2026-09-29T03:34:13Z"
    route.fulfill(response=response, json=payload)


@pytest.mark.parametrize(
    ("width", "reduced_motion"),
    [
        (1440, "no-preference"),
        (375, "no-preference"),
        (1440, "reduce"),
        (375, "reduce"),
    ],
    ids=["desktop-normal", "phone-normal", "desktop-reduced", "phone-reduced"],
)
def test_history_switch_motion(
    browser: Browser,
    workspace_servers: tuple[str, str],
    width: int,
    reduced_motion: str,
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="en-US",
        viewport={"width": width, "height": 870},
        reduced_motion=reduced_motion,
        timezone_id="Asia/Taipei",
    )
    page = context.new_page()
    gates: list[DeferredRoute] = []
    try:
        response = page.request.post(
            f"{base}/api/resumes",
            data={"documentLocale": "en", "template": "minimal", "title": "History"},
        )
        assert response.ok, response.text()
        created = response.json()["data"]["resume"]
        resume_id = created["id"]
        payload = {
            key: created[key]
            for key in (
                "title",
                "documentLocale",
                "resume",
                "jobBrief",
                "typography",
                "template",
                "templateSettings",
            )
        }
        names = ["History B", "History A", "Current resume"]
        for name, item_count in zip(names, [8, 22, 4], strict=True):
            payload["resume"]["basic"]["name"] = name
            payload["resume"]["sections"] = [
                {
                    "id": "experience",
                    "kind": "experience",
                    "title": "Experience",
                    "items": [
                        {
                            "id": f"experience-{index}",
                            "company": f"{name} Company {index}",
                            "position": "Software Engineer",
                            "location": "Taipei",
                            "period": "2020 - 2024",
                            "description": (
                                "Built a resume workspace for structured editing."
                            ),
                            "highlights": [
                                "Implemented document history "
                                "and reliable checkpoints.",
                                "Shipped a preview with pagination and PDF export.",
                            ],
                        }
                        for index in range(1, item_count + 1)
                    ],
                }
            ]
            saved = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
            assert saved.ok, saved.text()
        page.route(f"**/api/resumes/{resume_id}", _fixed_saved_at)
        page.route(f"**/api/resumes/{resume_id}/versions", _fixed_saved_at)
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        page.locator(
            '[data-slot="save-status-group"] [data-slot="popover-trigger"]'
        ).click()
        popover = page.get_by_role("dialog", name="Version History", exact=True)
        expect(popover).to_be_visible()
        for scenario, version_id, row_index, name in [
            ("latest-to-history", "3", 1, names[1]),
            ("history-to-history", "2", 2, names[0]),
            ("history-to-latest", None, 0, names[2]),
        ]:
            gate = None
            if version_id:
                gate = DeferredRoute(
                    page, f"**/api/resumes/{resume_id}/versions/{version_id}"
                )
                gates.append(gate)
                popover.get_by_role("button").nth(row_index).click()
                gate.wait()
            _record_history_motion(page)
            if gate:
                gate.release(_fixed_saved_at)
            else:
                popover.get_by_role("button").nth(row_index).click()
            expect(page.locator(".resume-page").first).to_contain_text(name)
            frames = _finish_history_motion(page)
            tops = [frame["viewportTop"] for frame in frames]
            intermediate = {
                top
                for top in tops
                if min(tops[0], tops[-1]) + 0.5 < top < max(tops[0], tops[-1]) - 0.5
            }
            if scenario == "history-to-history":
                assert max(tops) - min(tops) <= 1, tops
            else:
                assert (
                    len(intermediate) == 0
                    if reduced_motion == "reduce"
                    else (len(intermediate) >= 2)
                ), tops
            assert all(
                abs(frame["menuHeight"] - frames[0]["menuHeight"]) <= 1
                and all(
                    abs(row["top"] - initial["top"]) <= 1
                    for row, initial in zip(
                        frame["rows"], frames[0]["rows"], strict=True
                    )
                )
                for frame in frames
            ), frames
            assert [
                frame["text"]
                for index, frame in enumerate(frames)
                if index == 0 or frame["text"] != frames[index - 1]["text"]
            ] == [frames[0]["text"], name]
            assert all(
                frame["paperTop"] - frame["viewportTop"]
                == pytest.approx(
                    frames[0]["paperTop"] - frames[0]["viewportTop"], abs=1
                )
                for frame in frames
            )
        popover.get_by_role("button").nth(1).click()
        expect(page.locator(".resume-page").first).to_contain_text("History A")
        repeated_requests: list[str] = []
        page.on(
            "request",
            lambda request: (
                repeated_requests.append(request.url)
                if request.url.endswith(f"/resumes/{resume_id}/versions/3")
                else None
            ),
        )
        _record_history_motion(page)
        popover.get_by_role("button").nth(1).click()
        repeated_frames = _finish_history_motion(page)
        assert repeated_requests == []
        assert all(
            not row["disabled"] for frame in repeated_frames for row in frame["rows"]
        )
        page.keyboard.press("Escape")
        expect(popover).not_to_be_visible()
        return_button = page.get_by_role("button", name="Back to latest", exact=True)
        return_button.focus()
        return_button.press("Enter")
        expect(page.locator(".resume-page").first).to_contain_text("Current resume")
        expect(page.locator('[data-slot="document-canvas-viewport"]')).to_be_focused()
    finally:
        for gate in gates:
            gate.release()
        context.close()
