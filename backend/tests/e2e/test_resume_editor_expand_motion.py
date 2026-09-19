from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_resume_editor_sorting import (
    PANE,
    _item,
    _item_toggle,
    _section,
    _section_toggle,
    _settle,
)
from tests.e2e.test_resume_editor_sorting import (
    sorting_workspace as sorting_workspace,
)

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.mark.parametrize("reopen", ["same-section", "switch-section"])
@pytest.mark.parametrize(
    "sorting_workspace",
    [{"locale": "zh", "width": 1440, "height": 1100}],
    indirect=True,
)
def test_wrapped_content_reopens_without_a_jump_after_the_height_animation(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
    reopen: str,
) -> None:
    page, base, resume_id, messages = sorting_workspace
    text = (
        "具备良好的学习与协作能力，参与简历编辑器的设计与实现，"
        "负责结构化表单、文档预览和可访问性改进，熟悉多语言界面与浏览器性能分析，"
        "能够独立完成需求评估、功能开发和回归验证"
    )
    response = page.request.get(f"{base}/api/resumes/{resume_id}")
    assert response.ok, response.text()
    saved = response.json()["data"]["resume"]
    payload = {
        key: saved[key]
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
    payload["resume"]["sections"] = [
        saved["resume"]["sections"][0],
        {
            "id": "summary",
            "kind": "simple_list",
            "title": "自我评价",
            "items": [
                {"id": "summary-content", "content": f"<ul><li>{text}</li></ul>"}
            ],
        },
    ]
    response = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
    assert response.ok, response.text()
    page.evaluate(
        """() => localStorage.setItem('reseno-workspace-layout-v1',
          JSON.stringify({editorWidth: 420, agentWidth: 360}))"""
    )
    page.reload(wait_until="networkidle")
    page.wait_for_function(
        """selector => Math.abs(
          document.querySelector(selector).getBoundingClientRect().width - 420
        ) < 1""",
        arg=PANE,
    )
    section = _section(page, "summary")
    toggle = _section_toggle(section)
    toggle.click()
    editor = section.get_by_role(
        "textbox", name=messages["fieldLabels"]["content"], exact=True
    )
    expect(editor).to_have_text(text)
    _settle(page)
    if reopen == "same-section":
        toggle.click()
    else:
        _section_toggle(_section(page, "experience")).click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    _settle(page)

    section.evaluate(
        """section => {
          const observation = {done: false};
          window.__editorExpansionCompletion = observation;
          const nextFrame = () => new Promise(requestAnimationFrame);
          const started = async event => {
            const content = event.target;
            if (!content.matches('[data-slot="collapsible-content"]')) return;
            const animation = content.getAnimations().find(candidate => {
              const frames = candidate.effect?.getKeyframes();
              return candidate.effect?.target === content &&
                frames?.at(-1)?.height !== undefined;
            });
            if (!animation) return;
            section.removeEventListener('animationstart', started);
            const end = animation.effect.getKeyframes().at(-1);
            observation.keyframeHeight = end.height;
            observation.duration = animation.effect.getComputedTiming().duration;
            try {
              await animation.finished;
              await nextFrame();
              observation.firstHeight = content.getBoundingClientRect().height;
              await nextFrame();
              observation.finalHeight = content.getBoundingClientRect().height;
              observation.state = content.dataset.state;
            } catch (error) {
              observation.error = String(error);
            } finally {
              observation.done = true;
            }
          };
          section.addEventListener('animationstart', started);
        }"""
    )
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    page.wait_for_function("window.__editorExpansionCompletion.done", timeout=5_000)
    observation = page.evaluate("window.__editorExpansionCompletion")
    assert "error" not in observation, observation
    assert observation["duration"] > 0, observation
    assert observation["state"] == "open", observation
    assert observation["keyframeHeight"].endswith("px"), observation
    target_height = float(observation["keyframeHeight"].removesuffix("px"))
    assert target_height > 0, observation
    assert observation["firstHeight"] == pytest.approx(target_height, abs=2), (
        observation
    )
    assert observation["finalHeight"] == pytest.approx(target_height, abs=2), (
        observation
    )
    expect(editor).to_have_text(text)


@pytest.mark.parametrize(
    "sorting_workspace",
    [
        {"locale": "zh", "width": 1280, "reduced_motion": "no-preference"},
        {"locale": "en", "width": 1440, "reduced_motion": "reduce"},
        {"locale": "zh", "width": 390, "height": 844, "touch": True},
    ],
    indirect=True,
    ids=["animated", "reduced-motion", "touch"],
)
def test_item_expansion_keeps_title_and_controls_still_while_summary_collapses(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, _, _, messages = sorting_workspace
    _section_toggle(_section(page, "experience")).click()
    _settle(page)
    item = _item(page, "experience-1")
    toggle = _item_toggle(item)
    field = item.get_by_role(
        "textbox", name=messages["fieldLabels"]["company"], exact=True
    )
    reduced_motion = page.evaluate(
        "matchMedia('(prefers-reduced-motion: reduce)').matches"
    )
    touch = page.evaluate("matchMedia('(pointer: coarse)').matches")

    for _ in range(2):
        item.evaluate(
            """item => {
              const header = item.querySelector('[data-slot="editor-item-header"]');
              const toggle = header.querySelector(
                '[data-slot="editor-toggle-trigger"]');
              const read = () => {
                const origin = header.getBoundingClientRect();
                const bounds = element => {
                  if (!element) return null;
                  const box = element.getBoundingClientRect();
                  return {x: box.x - origin.x, y: box.y - origin.y,
                    height: box.height, width: box.width};
                };
                const heading = header.querySelector('h4:not(.sr-only)');
                const editor = header.querySelector('.editor-item-title');
                const text = heading?.querySelector('span') ?? heading ??
                  editor?.querySelector('p') ?? editor;
                let title = null;
                if (text) {
                  const range = document.createRange();
                  range.selectNodeContents(text);
                  title = bounds(range);
                }
                const summary = header.querySelector('.editor-item-summary');
                return {title, toggle: bounds(toggle), summary: bounds(summary),
                  fontSize: text ? getComputedStyle(text).fontSize : null,
                  summaryMargin: summary ?
                    parseFloat(getComputedStyle(summary).marginTop) : null,
                  buttons: Array.from(header.querySelectorAll('button'), bounds),
                  summaryOpacity: summary ?
                    Number(getComputedStyle(summary).opacity) : null,
                  body: bounds(item.querySelector('[data-slot="collapsible-content"]')),
                  durations: item.getAnimations({subtree: true}).map(animation =>
                    animation.effect.getComputedTiming().duration)};
              };
              const observation = {done: false, frames: [read()]};
              window.__itemExpansionFrames = observation;
              toggle.addEventListener('click', () => {
                const start = performance.now();
                const sample = () => {
                  observation.frames.push(read());
                  if (performance.now() - start < 600) requestAnimationFrame(sample);
                  else observation.done = true;
                };
                requestAnimationFrame(sample);
              }, {once: true});
            }"""
        )
        toggle.click()
        expect(field).to_have_text("Atlas Lab")
        page.wait_for_function("window.__itemExpansionFrames.done")
        frames = page.evaluate("window.__itemExpansionFrames.frames")
        initial, final = frames[0], frames[-1]
        assert initial["summary"]["height"] > 0, initial
        for frame in frames:
            assert frame["title"] is not None, frame
            assert frame["summary"] is not None, frame
            assert frame["fontSize"] == initial["fontSize"], frame
            for axis in ("x", "y"):
                assert frame["title"][axis] == pytest.approx(
                    initial["title"][axis], abs=1.5
                ), frame
                position = frame["toggle"][axis]
                original = initial["toggle"][axis]
                if touch and axis == "y":
                    position -= frame["summary"]["height"] + frame["summaryMargin"]
                    original -= initial["summary"]["height"] + initial["summaryMargin"]
                assert position == pytest.approx(original, abs=0.5), frame
            for index, button in enumerate(frame["buttons"]):
                if touch:
                    assert min(button["width"], button["height"]) >= 44, frame
                for other in frame["buttons"][index + 1 :]:
                    overlap_x = min(
                        button["x"] + button["width"], other["x"] + other["width"]
                    ) - max(button["x"], other["x"])
                    overlap_y = min(
                        button["y"] + button["height"], other["y"] + other["height"]
                    ) - max(button["y"], other["y"])
                    assert overlap_x <= 0.5 or overlap_y <= 0.5, frame
        assert final["summary"]["height"] <= 0.5, final
        assert final["summaryOpacity"] == 0, final
        if reduced_motion:
            assert all(not frame["durations"] for frame in frames[1:]), frames
        else:
            assert any(
                0.5 < frame["summary"]["height"] < initial["summary"]["height"] - 0.5
                and 0 < frame["summaryOpacity"] < 1
                for frame in frames[1:]
            ), frames
        expect(toggle).to_be_focused()
        expect(field).not_to_be_focused()
        toggle.click()
        _settle(page)
        expect(toggle).to_have_attribute("aria-expanded", "false")

    toggle.click()
    page.wait_for_timeout(45)
    toggle.click()
    page.wait_for_timeout(45)
    toggle.click()
    _settle(page)
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(field).to_have_text("Atlas Lab")
    expect(field).to_be_visible()
    expect(toggle).to_be_focused()
    toggle.click()
    _settle(page)
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(field).not_to_be_visible()
