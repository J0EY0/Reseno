from __future__ import annotations

import json
import os

import pytest
from playwright.sync_api import Browser, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.e2e.browser_support import browser_session

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
def test_template_gallery_default_actions_do_not_animate_during_theme_changes(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        color_scheme="light",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/templates", wait_until="networkidle")
        default_action = page.get_by_role(
            "button",
            name="设为默认模板",
            exact=True,
        ).first
        theme_toggle = page.get_by_role(
            "button",
            name="切换日间 / 夜间模式",
            exact=True,
        )
        expect(default_action).to_be_visible()
        expect(theme_toggle).to_be_visible()

        result = page.evaluate(
            """
            async ([button, toggle]) => {
              const initialDark = document.documentElement.classList.contains('dark');
              const frames = [];
              const originalButton = button;
              const startedAt = performance.now();
              toggle.click();
              await new Promise(resolve => {
                const sample = now => {
                  const rect = button.getBoundingClientRect();
                  frames.push({
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                    connected: button.isConnected,
                    transitions: button.getAnimations().flatMap(animation =>
                      animation instanceof CSSTransition
                        ? [animation.transitionProperty]
                        : []
                    ),
                  });
                  if (now - startedAt >= 320 && frames.length >= 5) {
                    resolve();
                    return;
                  }
                  requestAnimationFrame(sample);
                };
                requestAnimationFrame(sample);
              });
              return {
                initialDark,
                finalDark: document.documentElement.classList.contains('dark'),
                sameNode: originalButton === button,
                frames,
              };
            }
            """,
            [default_action.element_handle(), theme_toggle.element_handle()],
        )

        assert result["finalDark"] is not result["initialDark"], result
        assert result["sameNode"], result
        assert len(result["frames"]) >= 5, result
        assert all(frame["connected"] for frame in result["frames"]), result
        assert not any(frame["transitions"] for frame in result["frames"]), result
        for key in ("x", "y", "width", "height"):
            values = [frame[key] for frame in result["frames"]]
            assert max(values) - min(values) <= 1, (key, result)
    finally:
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize("initial_theme", ["light", "dark"])
def test_resume_agent_composer_actions_do_not_animate_during_theme_changes(
    browser: Browser,
    workspace_servers: tuple[str, str],
    initial_theme: str,
) -> None:
    frontend_url, resume_id = workspace_servers
    model_config_id = "llm-agent-theme-transition"
    model_nickname = "Agent theme transition"
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        color_scheme="light",
        viewport={"width": 1440, "height": 900},
    )
    session = browser_session
    assert session
    context.add_init_script(
        script=(
            "window.localStorage.setItem('reseno-auth-session', "
            f"{json.dumps(json.dumps(session))});"
        )
    )
    context.add_init_script(
        script=f"localStorage.setItem('reseno-theme', {json.dumps(initial_theme)});"
    )
    page = context.new_page()

    def fulfill_workspace(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["theme"] = initial_theme
        payload["data"]["modelConfigs"] = [
            {
                "id": model_config_id,
                "provider": "deepseek",
                "nickname": model_nickname,
                "model": "deepseek-v4-pro",
                "supportsTools": True,
            }
        ]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = model_config_id
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    page.route("**/api/workspace/pages/resume-editor", fulfill_workspace)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        agent_toggle = page.locator(
            '.resume-workspace [data-slot="agent-panel-toggle"]'
        )
        live_body = page.locator(
            '#resume-detail-agent-panel [data-slot="agent-panel-live-body"]'
        )
        composer = live_body.locator('[data-slot="agent-composer"]')
        theme_toggle = page.get_by_role(
            "button",
            name="切换日间 / 夜间模式",
            exact=True,
        )
        expect(agent_toggle).to_be_visible()
        agent_toggle.click()
        expect(live_body).to_have_attribute("aria-hidden", "false")
        expect(composer).to_be_visible()
        attachment_button = composer.get_by_role(
            "button",
            name="添加附件",
            exact=True,
        )
        model_button = composer.get_by_role(
            "button",
            name=model_nickname,
            exact=True,
        )
        expect(attachment_button).to_be_visible()
        expect(model_button).to_be_visible()
        expect(theme_toggle).to_be_visible()

        result = page.evaluate(
            """
            async ([attachmentButton, modelButton, toggle]) => {
              const buttons = [attachmentButton, modelButton];
              const initialDark = document.documentElement.classList.contains('dark');
              const frames = [];
              const startedAt = performance.now();
              toggle.click();
              await new Promise(resolve => {
                const sample = now => {
                  const themeColor = getComputedStyle(document.body).color;
                  frames.push({
                    dark: document.documentElement.classList.contains('dark'),
                    themeColor,
                    buttons: buttons.map(button => ({
                      color: getComputedStyle(button).color,
                      connected: button.isConnected,
                      transitions: button.getAnimations().flatMap(animation =>
                        animation instanceof CSSTransition
                          ? [animation.transitionProperty]
                          : []
                      ),
                    })),
                  });
                  if (now - startedAt >= 320 && frames.length >= 5) {
                    resolve();
                    return;
                  }
                  requestAnimationFrame(sample);
                };
                requestAnimationFrame(sample);
              });
              return {
                buttonCount: buttons.length,
                declaredTransitions: buttons.map(
                  button => getComputedStyle(button).transitionProperty
                ),
                finalDark: document.documentElement.classList.contains('dark'),
                frames,
                initialDark,
              };
            }
            """,
            [
                attachment_button.element_handle(),
                model_button.element_handle(),
                theme_toggle.element_handle(),
            ],
        )

        assert result["finalDark"] is not result["initialDark"], result
        assert result["buttonCount"] == 2, result
        assert len(result["frames"]) >= 5, result
        assert all(
            frame["dark"] == result["finalDark"] for frame in result["frames"]
        ), result
        assert all(
            button["connected"]
            for frame in result["frames"]
            for button in frame["buttons"]
        ), result
        assert all(
            button["color"] == frame["themeColor"]
            for frame in result["frames"]
            for button in frame["buttons"]
        ), result
        assert not any(
            button["transitions"]
            for frame in result["frames"]
            for button in frame["buttons"]
        ), result
        assert all(
            transition != "none" for transition in result["declaredTransitions"]
        ), result
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_workspace_theme_changes_do_not_animate_visible_palette_properties(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        color_scheme="light",
        viewport={"width": 1440, "height": 900},
    )
    session = browser_session
    assert session
    context.add_init_script(
        script=(
            "window.localStorage.setItem('reseno-auth-session', "
            f"{json.dumps(json.dumps(session))});"
        )
    )
    page = context.new_page()
    routes = [
        "/resume",
        "/templates",
        "/models",
        "/trash",
        f"/resume/{resume_id}",
        "/template/minimal",
    ]

    try:
        failures: dict[str, list[dict[str, str]]] = {}
        for route_path in routes:
            page.goto(f"{frontend_url}{route_path}", wait_until="networkidle")
            theme_toggle = page.get_by_role(
                "button",
                name="切换日间 / 夜间模式",
                exact=True,
            )
            assert theme_toggle.count() == 1, route_path
            expect(theme_toggle).to_be_visible()
            page.evaluate(
                """
                () => new Promise(resolve => {
                  requestAnimationFrame(() => requestAnimationFrame(resolve));
                })
                """
            )

            transitions = page.evaluate(
                """
                async toggle => {
                  const paletteProperties = new Set([
                    'background-color',
                    'border-block-end-color',
                    'border-block-start-color',
                    'border-bottom-color',
                    'border-inline-end-color',
                    'border-inline-start-color',
                    'border-left-color',
                    'border-right-color',
                    'border-top-color',
                    'box-shadow',
                    'caret-color',
                    'color',
                    'fill',
                    'outline-color',
                    'stroke',
                    'text-decoration-color',
                  ]);
                  const events = [];
                  const seen = new Set();
                  const describe = element => {
                    const label =
                      element.getAttribute('aria-label') ||
                      element.getAttribute('data-slot') ||
                      element.textContent?.trim().replace(/\\s+/g, ' ').slice(0, 80) ||
                      element.tagName.toLowerCase();
                    return `${element.tagName.toLowerCase()}:${label}`;
                  };
                  const onTransitionRun = event => {
                    if (
                      !(event.target instanceof HTMLElement) ||
                      !paletteProperties.has(event.propertyName)
                    ) {
                      return;
                    }
                    const rect = event.target.getBoundingClientRect();
                    const style = getComputedStyle(event.target);
                    if (
                      rect.width === 0 ||
                      rect.height === 0 ||
                      style.display === 'none' ||
                      style.visibility === 'hidden'
                    ) {
                      return;
                    }
                    const key = `${describe(event.target)}:${event.propertyName}`;
                    if (!seen.has(key)) {
                      seen.add(key);
                      events.push({
                        element: describe(event.target),
                        property: event.propertyName,
                      });
                    }
                  };
                  document.addEventListener('transitionrun', onTransitionRun, true);
                  toggle.click();
                  await new Promise(resolve => setTimeout(resolve, 320));
                  document.removeEventListener(
                    'transitionrun',
                    onTransitionRun,
                    true,
                  );
                  return events;
                }
                """,
                theme_toggle.element_handle(),
            )
            if transitions:
                failures[route_path] = transitions

        assert failures == {}
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_settings_theme_options_switch_palette_without_lagging_controls(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        color_scheme="light",
        viewport={"width": 1440, "height": 900},
    )
    session = browser_session
    assert session
    context.add_init_script(
        script=(
            "window.localStorage.setItem('reseno-auth-session', "
            f"{json.dumps(json.dumps(session))});"
        )
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/settings", wait_until="networkidle")
        theme_group = page.get_by_role("group", name="主题", exact=True)
        expect(theme_group).to_be_visible()
        theme_group_handle = theme_group.element_handle()
        initial_dark = page.locator("html").evaluate(
            "element => element.classList.contains('dark')"
        )
        target_label = "日间" if initial_dark else "夜间"
        theme_group.get_by_role("combobox", name="主题", exact=True).click()
        target = page.get_by_role("option", name=target_label, exact=True)
        expect(target).to_be_visible()

        result = page.evaluate(
            """
            async ([group, target]) => {
              const buttons = [...group.querySelectorAll('button')];
              const initialDark = document.documentElement.classList.contains('dark');
              const frames = [];
              const startedAt = performance.now();
              target.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Enter',
                bubbles: true,
              }));
              await new Promise(resolve => {
                const sample = now => {
                  frames.push({
                    dark: document.documentElement.classList.contains('dark'),
                    transitions: buttons.flatMap(button =>
                      button.getAnimations().flatMap(animation =>
                        animation instanceof CSSTransition
                          ? [animation.transitionProperty]
                          : []
                      )
                    ),
                  });
                  if (now - startedAt >= 220 && frames.length >= 5) {
                    resolve();
                    return;
                  }
                  requestAnimationFrame(sample);
                };
                requestAnimationFrame(sample);
              });
              return {
                declaredTransitions: buttons.map(
                  button => getComputedStyle(button).transitionProperty
                ),
                finalDark: document.documentElement.classList.contains('dark'),
                frames,
                initialDark,
                selectedValue: group.querySelector('[role="combobox"]')
                  ?.textContent?.trim(),
              };
            }
            """,
            [theme_group_handle, target.element_handle()],
        )

        assert result["finalDark"] is not result["initialDark"], result
        assert result["selectedValue"] == target_label, result
        assert len(result["frames"]) >= 5, result
        assert all(
            frame["dark"] == result["finalDark"] for frame in result["frames"]
        ), result
        assert not any(frame["transitions"] for frame in result["frames"]), result
        assert all(
            transition != "none" for transition in result["declaredTransitions"]
        ), result
    finally:
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("saved_theme", "os_color_scheme", "expects_dark"),
    [
        ("dark", "light", True),
        ("light", "dark", False),
        ("system", "dark", True),
    ],
)
def test_theme_bootstrap_matches_saved_preference_before_react_mounts(
    browser: Browser,
    workspace_servers: tuple[str, str],
    saved_theme: str,
    os_color_scheme: str,
    expects_dark: bool,
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(color_scheme=os_color_scheme)
    context.add_init_script(
        script=f"localStorage.setItem('reseno-theme', {json.dumps(saved_theme)});"
    )
    page = context.new_page()
    blocked_main_requests = 0

    def block_react_entry(route: Route) -> None:
        nonlocal blocked_main_requests
        blocked_main_requests += 1
        route.abort()

    page.route("**/src/main.tsx*", block_react_entry)

    try:
        page.goto(frontend_url, wait_until="domcontentloaded")
        bootstrap_state = page.locator("html").evaluate(
            """
            element => ({
              colorScheme: element.style.colorScheme,
              hasDarkClass: element.classList.contains('dark'),
              rootChildCount: document.querySelector('#root')?.childElementCount,
            })
            """
        )

        assert blocked_main_requests == 1
        assert bootstrap_state["rootChildCount"] == 0
        assert bootstrap_state["hasDarkClass"] is expects_dark
        assert bootstrap_state["colorScheme"] == ("dark" if expects_dark else "light")
    finally:
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_login_input_group_autofill_respects_component_surface(
    browser: Browser,
    workspace_servers: tuple[str, str],
    theme: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(locale="en-US")
    context.add_init_script(
        script=f"localStorage.setItem('reseno-theme', {json.dumps(theme)});"
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/login", wait_until="networkidle")
        controls = [page.locator("#username"), page.locator("#password")]
        cdp = context.new_cdp_session(page)
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        document_node_id = cdp.send("DOM.getDocument")["root"]["nodeId"]

        for selector, control in zip(("#username", "#password"), controls, strict=True):
            node_id = cdp.send(
                "DOM.querySelector",
                {"nodeId": document_node_id, "selector": selector},
            )["nodeId"]
            assert node_id
            cdp.send(
                "CSS.forcePseudoState",
                {"nodeId": node_id, "forcedPseudoClasses": ["autofill"]},
            )
            assert control.evaluate("element => element.matches(':-webkit-autofill')")

        def read_autofill_styles() -> list[dict[str, str]]:
            return page.locator("#username, #password").evaluate_all(
                """
                elements => elements.map(element => {
                  const styles = getComputedStyle(element)
                  return {
                    backgroundClip: styles.backgroundClip,
                    caretColor: styles.caretColor,
                    textFillColor: styles.webkitTextFillColor,
                  }
                })
                """
            )

        expected_text_color = page.locator("body").evaluate(
            "element => getComputedStyle(element).color"
        )
        assert (
            read_autofill_styles()
            == [
                {
                    "backgroundClip": "text",
                    "caretColor": expected_text_color,
                    "textFillColor": expected_text_color,
                }
            ]
            * 2
        )

        page.emulate_media(forced_colors="active")
        canvas_text = page.locator("body").evaluate(
            "element => getComputedStyle(element).color"
        )
        assert (
            read_autofill_styles()
            == [
                {
                    "backgroundClip": "border-box",
                    "caretColor": canvas_text,
                    "textFillColor": canvas_text,
                },
            ]
            * 2
        )
    finally:
        context.close()
