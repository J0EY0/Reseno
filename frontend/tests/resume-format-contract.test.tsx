import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ResumeFormatPopover } from "@/components/editor/resume-format-popover";
import { getTemplateEditorMessages } from "@/components/templates/editor/editor-messages";
import { TemplateStyleTabs } from "@/components/templates/template-style-tabs";
import { TemplateTypographyTab } from "@/components/templates/editor/typography-tab";
import { AgentSettingsTab } from "@/components/agent-settings-tab";
import { Tabs } from "@/components/ui/tabs";
import { getMessagesSync, loadMessages } from "@/i18n";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import { getResumeFontSizeInPoints } from "@/lib/templates";
import { createResumeDetailTemplate } from "./helpers/resume-detail-fixtures";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restore: () => void;
beforeEach(async () => {
  await loadMessages("zh");
  restore = installPanelBrowserApis();
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});
it.each(["en", "zh"] as const)(
  "offers localized Noto font values from the actual resume format controls: %s",
  async (locale) => {
    const t = getMessagesSync(locale);
    const template = createResumeDetailTemplate("minimal");
    const other = createResumeDetailTemplate("other");
    const onTypographyChange = vi.fn(),
      onTemplateChange = vi.fn();
    render(
      <ResumeFormatPopover
        t={t}
        template={template.id}
        templates={[template, other]}
        typography={template.typography}
        settings={template.settings}
        hasTemplateStyleOverrides={false}
        onRestoreTemplateDefaults={vi.fn()}
        onTemplateChange={onTemplateChange}
        onTypographyChange={onTypographyChange}
        onTemplateSettingsChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: t.format }));
    expect(screen.getAllByRole("combobox")).toHaveLength(3);
    for (const [label, width, option] of [
      [t.applyTemplate, "w-32", "other"],
      [t.fontFamily, "w-44", t.fontNotoSans],
      [t.fontSize, "w-24", `${getResumeFontSizeInPoints(18)} pt`],
    ]) {
      const trigger = screen.getByRole("combobox", { name: label });
      expect(trigger.getAttribute("data-size")).toBe("sm");
      expect(
        Array.from(trigger.classList).filter((token) =>
          /^w-(?:\d+|\[)/.test(token),
        ),
      ).toEqual([width]);
      fireEvent.keyDown(trigger, { key: "ArrowDown" });
      const list = screen.getByRole("listbox");
      expect(list.getAttribute("data-align")).toBe("end");
      for (const token of [
        "w-[var(--radix-select-trigger-width)]",
        "min-w-[var(--radix-select-trigger-width)]",
        "data-[side=bottom]:translate-y-1",
      ])
        expect(list.classList.contains(token)).toBe(true);
      await waitFor(() =>
        expect(list.parentElement?.style.transform).toBe("translate(0px, 0px)"),
      );
      if (label === t.fontFamily) {
        expect(
          screen.getByRole("option", {
            name: locale === "en" ? "Noto Sans SC" : "思源黑体",
          }),
        ).toBeTruthy();
        expect(
          screen.getByRole("option", {
            name: locale === "en" ? "Noto Serif SC" : "思源宋体",
          }),
        ).toBeTruthy();
      }
      fireEvent.click(screen.getByRole("option", { name: option }));
    }
    expect(onTemplateChange).toHaveBeenCalledExactlyOnceWith("other");
    expect(onTypographyChange.mock.calls).toEqual([
      [{ ...template.typography, fontFamily: "noto_sans_sc" }],
      [{ ...template.typography, fontSize: 18 }],
    ]);
  },
);
it.each(["en", "zh"] as const)(
  "preserves canonical font values in the template typography selector: %s",
  (locale) => {
    const t = getTemplateEditorMessages(locale, getMessagesSync(locale));
    const template = createResumeDetailTemplate("custom");
    const update = vi.fn();
    render(
      <TemplateStyleTabs defaultValue="typography">
        <TemplateTypographyTab
          t={t}
          template={template}
          onUpdateTemplate={update}
        />
      </TemplateStyleTabs>,
    );
    fireEvent.keyDown(screen.getByRole("combobox", { name: t.fontFamily }), {
      key: "ArrowDown",
    });
    expect(
      screen.getByRole("option", {
        name: locale === "en" ? "Noto Serif SC" : "思源宋体",
      }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("option", {
        name: locale === "en" ? "Noto Sans SC" : "思源黑体",
      }),
    );
    expect(update).toHaveBeenCalledExactlyOnceWith({
      typography: { ...template.typography, fontFamily: "noto_sans_sc" },
    });
  },
);
it.each(["en", "zh"] as const)(
  "labels the Agent follow option as resume language and publishes its canonical value: %s",
  (locale) => {
    const t = getMessagesSync(locale),
      settings = normalizeAgentSettings({ responseLanguage: "en" });
    const update = vi.fn();
    render(
      <Tabs defaultValue="agent">
        <AgentSettingsTab
          t={t}
          modelConfigs={[]}
          agentSettings={settings}
          onAgentSettingsChange={update}
        />
      </Tabs>,
    );
    fireEvent.keyDown(
      screen.getByRole("combobox", { name: t.agentResponseLanguage }),
      { key: "ArrowDown" },
    );
    fireEvent.click(
      screen.getByRole("option", {
        name: locale === "en" ? "Match Resume Language" : "跟随简历语言",
      }),
    );
    expect(update).toHaveBeenCalledExactlyOnceWith({
      ...settings,
      responseLanguage: "follow",
    });
    expect("followSystemLanguage" in t).toBe(false);
  },
);
