from __future__ import annotations

import json
import os
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_resume_editor_sorting import (
    ITEM,
    OVERLAY,
    PANE,
    SECTION,
    _expect_order,
    _item,
    _item_action,
    _item_title,
    _item_toggle,
    _save_and_read,
    _section,
    _section_title,
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


def _record_arrow_move(page: Page, button: Locator, row: Locator) -> list[float]:
    button.evaluate(
        """button => {
          const row = button.closest('[data-resume-item-id], [data-resume-section-id]');
          const pane = row.closest('.resume-editor-panel');
          const parent = row.parentElement;
          window.editorMoveSamples = {frames: [], done: false};
          button.addEventListener('click', () => {
            const started = performance.now();
            const initialIndex = [...parent.children].indexOf(row);
            let finished = false;
            const capture = () => {
              window.editorMoveSamples.frames.push(
                row.getBoundingClientRect().top + pane.scrollTop
              );
            };
            const observer = new MutationObserver(async () => {
              if ([...parent.children].indexOf(row) === initialIndex) return;
              observer.disconnect();
              const animations = [...parent.children].flatMap(item =>
                item.getAnimations().filter(animation =>
                  animation.id === 'editor-reorder'
                )
              );
              for (const animation of animations) animation.pause();
              await Promise.all(animations.map(animation => animation.ready));
              if (animations.length) {
                for (const progress of [0.2, 0.4, 0.6, 0.8]) {
                  for (const animation of animations) {
                    animation.currentTime = Number(
                      animation.effect.getTiming().duration
                    ) * progress;
                  }
                  await new Promise(requestAnimationFrame);
                  capture();
                }
                for (const animation of animations) animation.play();
                await Promise.all(animations.map(animation => animation.finished));
              }
              await new Promise(requestAnimationFrame);
              finished = true;
            });
            observer.observe(parent, {childList: true});
            function sample() {
              capture();
              if (performance.now() - started < 400 || !finished) {
                requestAnimationFrame(sample);
              } else window.editorMoveSamples.done = true;
            }
            sample();
          }, {once: true});
        }"""
    )
    button.click()
    page.wait_for_function("window.editorMoveSamples.done")
    frames = page.evaluate("window.editorMoveSamples.frames")
    _settle(page)
    final_top = row.evaluate(
        "element => element.getBoundingClientRect().top + "
        "element.closest('.resume-editor-panel').scrollTop"
    )
    assert frames[-1] == pytest.approx(final_top, abs=1)
    low, high = sorted((frames[0], final_top))
    assert high - low > 20
    intermediate = [top for top in frames if low + 1 < top < high - 1]
    reduced_motion = page.evaluate(
        "matchMedia('(prefers-reduced-motion: reduce)').matches"
    )
    if reduced_motion:
        assert intermediate == []
    else:
        assert len(intermediate) >= 2, json.dumps(frames)
    return frames


@pytest.mark.parametrize(
    "sorting_workspace",
    [
        {"height": 760, "item_groups": 4, "reduced_motion": "no-preference"},
        {"height": 760, "item_groups": 4, "reduced_motion": "reduce"},
    ],
    indirect=True,
    ids=["motion", "reduced-motion"],
)
def test_arrow_moves_keep_focus_and_expansion_and_scroll_only_when_needed(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
    pane = page.locator(PANE)
    experience = _section(page, "experience")
    education = _section(page, "education")
    project = _section(page, "project")
    expect(
        experience.get_by_role(
            "button", name=f"Experience: {messages['moveSectionUp']}", exact=True
        )
    ).to_be_disabled()
    expect(
        project.get_by_role(
            "button", name=f"Projects: {messages['moveSectionDown']}", exact=True
        )
    ).to_be_disabled()
    education_title = _section_title(education)
    _section_toggle(education).click()
    _settle(page)
    education_node = education.element_handle()
    assert education_node is not None
    section_up = education.get_by_role(
        "button", name=f"Education: {messages['moveSectionUp']}", exact=True
    )
    section_down = education.get_by_role(
        "button", name=f"Education: {messages['moveSectionDown']}", exact=True
    )
    before_scroll = pane.evaluate("element => element.scrollTop")
    _record_arrow_move(page, section_down, education)
    _expect_order(
        pane.locator(SECTION),
        "data-resume-section-id",
        ["experience", "project", "education"],
    )
    expect(section_down).to_be_disabled()
    expect(education_title).to_be_focused()
    expect(_section_toggle(education)).to_have_attribute("aria-expanded", "true")
    assert education_node.evaluate("element => element.isConnected")
    assert pane.evaluate("element => element.scrollTop") == pytest.approx(
        before_scroll, abs=1
    )
    section_up.click()
    _settle(page)
    expect(section_up).to_be_focused()
    expect(_section_toggle(education)).to_have_attribute("aria-expanded", "true")
    section_up.click()
    _settle(page)
    expect(section_up).to_be_disabled()
    expect(education_title).to_be_focused()
    _expect_order(
        pane.locator(SECTION),
        "data-resume-section-id",
        ["education", "experience", "project"],
    )
    assert pane.evaluate("element => element.scrollTop") == pytest.approx(
        before_scroll, abs=1
    )

    _section_toggle(experience).click()
    _settle(page)
    first = _item(page, "experience-1")
    first_title = _item_title(first)
    _item_toggle(first).click()
    company = first.get_by_role(
        "textbox", name=messages["fieldLabels"]["company"], exact=True
    )
    company.fill("Preserved through arrow moves")
    _settle(page)
    field_node = company.element_handle()
    assert field_node is not None
    item_up = _item_action(first, messages["moveItemUp"])
    item_down = _item_action(first, messages["moveItemDown"])
    expect(item_up).to_be_disabled()
    expect(
        _item_action(_item(page, "experience-12"), messages["moveItemDown"])
    ).to_be_disabled()
    before_scroll = pane.evaluate("element => element.scrollTop")
    _record_arrow_move(page, item_down, first)
    expect(item_down).to_be_focused()
    expect(_item_toggle(first)).to_have_attribute("aria-expanded", "true")
    expect(_section_toggle(experience)).to_have_attribute("aria-expanded", "true")
    expect(company).to_have_text("Preserved through arrow moves")
    assert field_node.evaluate("element => element.isConnected")
    assert pane.evaluate("element => element.scrollTop") == pytest.approx(
        before_scroll, abs=1
    )
    item_up.click()
    _settle(page)
    expect(item_up).to_be_disabled()
    expect(first_title).to_be_focused()
    expect(_item_toggle(first)).to_have_attribute("aria-expanded", "true")
    _item_toggle(first).click()
    _settle(page)
    edge = _item(page, "experience-10")
    edge.evaluate(
        """element => {
          const pane = element.closest('.resume-editor-panel');
          const header = element.querySelector('[data-slot="editor-item-header"]');
          pane.scrollTo({
            top: pane.scrollTop + header.getBoundingClientRect().bottom -
              pane.getBoundingClientRect().bottom + 4,
            behavior: 'instant',
          });
        }"""
    )
    edge_title = _item_title(edge)
    expect(edge_title).to_be_in_viewport(ratio=1)
    edge_down = _item_action(edge, messages["moveItemDown"])
    before_scroll = pane.evaluate("element => element.scrollTop")
    edge_down.click()
    _settle(page)
    expect(edge_down).to_be_focused()
    expect(_item_toggle(edge)).to_have_attribute("aria-expanded", "false")
    expect(edge_title).to_be_in_viewport(ratio=1)
    after_scroll = pane.evaluate("element => element.scrollTop")
    assert after_scroll > before_scroll + 1
    edge_up = _item_action(edge, messages["moveItemUp"])
    edge_up.click()
    _settle(page)
    expect(edge_up).to_be_focused()
    assert pane.evaluate("element => element.scrollTop") == pytest.approx(
        after_scroll, abs=1
    )
    document = _save_and_read(page, base, resume_id)
    assert [section["id"] for section in document["sections"]] == [
        "education",
        "experience",
        "project",
    ]
    assert [item["id"] for item in document["sections"][1]["items"]] == [
        f"experience-{index}" for index in range(1, 13)
    ]
    assert (
        "Preserved through arrow moves"
        in document["sections"][1]["items"][0]["company"]
    )


@pytest.mark.parametrize("sorting_workspace", [{"item_groups": 3}], indirect=True)
def test_repeated_arrow_clicks_can_be_followed_immediately_by_dragging(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
    experience = _section(page, "experience")
    _section_toggle(experience).click()
    _settle(page)
    moving = _item(page, "experience-2")
    down = _item_action(moving, messages["moveItemDown"])
    for _ in range(2):
        box = down.bounding_box()
        assert box is not None
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        assert moving.evaluate(
            "element => element.getAnimations().some(animation => "
            "animation.id === 'editor-reorder' && animation.playState === 'running')"
        )
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-1", "experience-3", "experience-4", "experience-2"]
        + [f"experience-{index}" for index in range(5, 10)],
    )
    expect(down).to_be_focused()
    source_box = _item_title(moving).bounding_box()
    assert source_box is not None
    x = source_box["x"] + source_box["width"] / 3
    y = source_box["y"] + source_box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    try:
        page.mouse.move(x, y + 10, steps=2)
        expect(page.locator(OVERLAY)).to_be_visible()
        assert page.locator(PANE).evaluate(
            "element => !element.getAnimations({subtree: true}).some(animation => "
            "animation.id === 'editor-reorder' && animation.playState === 'running')"
        )
        target_box = _item_title(_item(page, "experience-5")).bounding_box()
        assert target_box is not None
        page.mouse.move(x, target_box["y"] + target_box["height"] * 0.8, steps=10)
    finally:
        page.mouse.up()
    expect(page.locator(OVERLAY)).to_have_count(0)
    _settle(page)
    order = [
        "experience-1",
        "experience-3",
        "experience-4",
        "experience-5",
        "experience-2",
    ] + [f"experience-{index}" for index in range(6, 10)]
    _expect_order(experience.locator(ITEM), "data-resume-item-id", order)
    document = _save_and_read(page, base, resume_id)
    assert [item["id"] for item in document["sections"][0]["items"]] == order


@pytest.mark.parametrize(
    "sorting_workspace",
    [{"locale": "zh", "width": 390, "height": 720, "touch": True, "item_groups": 5}],
    indirect=True,
)
def test_touch_arrow_moves_reveal_the_heading_below_the_sticky_toolbar(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
    experience = _section(page, "experience")
    _section_toggle(experience).tap()
    _settle(page)
    moving = _item(page, "experience-5")
    title = _item_title(moving)
    title.evaluate(
        """element => {
          const toolbar = document.querySelector('.app-shell--document > header');
          window.scrollTo({
            top: window.scrollY + element.getBoundingClientRect().top -
              toolbar.getBoundingClientRect().bottom - 16,
            behavior: 'instant',
          });
        }"""
    )
    before_scroll = page.evaluate("window.scrollY")
    assert before_scroll > 0
    up = _item_action(moving, messages["moveItemUp"])
    up.tap()
    _settle(page)
    page.wait_for_function(
        """() => {
          const title = document.querySelector(
            '[data-resume-item-id="experience-5"] [data-slot="editor-item-header"]'
          );
          const toolbar = document.querySelector('.app-shell--document > header');
          return title.getBoundingClientRect().top >=
            toolbar.getBoundingClientRect().bottom - 1;
        }"""
    )
    after_scroll = page.evaluate("window.scrollY")
    assert after_scroll < before_scroll - 1
    expect(up).to_be_focused()
    expect(_item_toggle(moving)).to_have_attribute("aria-expanded", "false")
    document = _save_and_read(page, base, resume_id)
    assert document["sections"][0]["items"][3]["id"] == "experience-5"
    title.evaluate(
        """element => {
          window.scrollBy({
            top: element.getBoundingClientRect().top - window.innerHeight / 3,
            behavior: 'instant',
          });
        }"""
    )
    after_scroll = page.evaluate("window.scrollY")
    down = _item_action(moving, messages["moveItemDown"])
    down.tap()
    _settle(page)
    expect(down).to_be_focused()
    assert page.evaluate("window.scrollY") == pytest.approx(after_scroll, abs=1)
