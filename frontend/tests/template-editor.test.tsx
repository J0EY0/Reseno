import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  TemplateColorField,
  TemplateNumberInput,
  TemplateSliderField,
} from "@/components/templates/editor/editor-fields";
import { getTemplateEditorMessages } from "@/components/templates/editor/editor-messages";
import { TemplateLayoutTab } from "@/components/templates/editor/layout-tab";
import { TemplateTypographyTab } from "@/components/templates/editor/typography-tab";
import { TemplateVisualTab } from "@/components/templates/editor/visual-tab";
import { TemplateMetadataDialog } from "@/components/templates/template-metadata-dialog";
import { TemplateStyleTabs } from "@/components/templates/template-style-tabs";
import enMessages from "@/i18n/locales/en.json";
import zhMessages from "@/i18n/locales/zh.json";
import {
  getBuiltInTemplates,
  getResumeFontSizeInPoints,
} from "@/lib/templates";
import type { ResumeTemplateDefinition } from "@/types/resume";

const en = getTemplateEditorMessages("en", enMessages);
const zh = getTemplateEditorMessages("zh", zhMessages);

afterEach(() => vi.unstubAllGlobals());

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

it("associates color and slider labels with the actual controls", () => {
  const onChange = vi.fn();
  render(
    <>
      <TemplateColorField label="Accent" value="#112233" onChange={onChange} />
      <TemplateSliderField
        label="Scale"
        min={0}
        max={100}
        step={1}
        value={50}
        unit="%"
        onChange={onChange}
      />
    </>,
  );
  const color = screen.getByLabelText<HTMLInputElement>("Accent");
  expect(color.type).toBe("color");
  expect(color.value).toBe("#112233");
  fireEvent.change(color, { target: { value: "#445566" } });
  expect(onChange).toHaveBeenCalledExactlyOnceWith("#445566");
  const slider = screen.getByRole("slider", { name: "Scale" });
  slider.focus();
  expect(document.activeElement).toBe(slider);
  fireEvent.keyDown(slider, { key: "ArrowRight" });
  expect(onChange).toHaveBeenLastCalledWith(51);
});

describe.each([en, zh])("Template editor in $templateName", (messages) => {
  it("labels the dialog, rejects blank names and submits metadata together", async () => {
    const onSave = vi.fn();
    render(
      <TemplateMetadataDialog
        messages={messages}
        template={{ name: "Original", description: "Description" }}
        onSave={onSave}
      />,
    );
    const trigger = screen.getByRole("button", {
      name: messages.editTemplateInfo,
    });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", {
      name: messages.editTemplateInfo,
    });
    const name = within(dialog).getByRole<HTMLInputElement>("textbox", {
      name: messages.templateName,
    });
    const description = within(dialog).getByRole<HTMLTextAreaElement>(
      "textbox",
      { name: messages.templateDescription },
    );
    const save = within(dialog).getByRole<HTMLButtonElement>("button", {
      name: messages.saveTemplateInfo,
    });
    expect(document.activeElement).toBe(name);
    expect([name.value, description.value]).toEqual([
      "Original",
      "Description",
    ]);
    for (const value of ["", "   "]) {
      fireEvent.change(name, { target: { value } });
      expect(save.disabled).toBe(true);
      fireEvent.submit(name.form!);
      expect(onSave).not.toHaveBeenCalled();
      expect(screen.getByRole("dialog")).toBe(dialog);
    }
    fireEvent.change(name, { target: { value: "  Updated  " } });
    fireEvent.change(description, { target: { value: "  New description\n" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledExactlyOnceWith({
      name: "Updated",
      description: "  New description\n",
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it.each(["cancel", "escape"])(
    "discards edits on %s and reopens with current metadata",
    (close) => {
      const onSave = vi.fn();
      const props = {
        messages,
        template: { name: "Original", description: "Description" },
        onSave,
      };
      const view = render(<TemplateMetadataDialog {...props} />);
      const open = () =>
        fireEvent.click(
          screen.getByRole("button", { name: messages.editTemplateInfo }),
        );
      open();
      fireEvent.change(
        screen.getByRole("textbox", { name: messages.templateName }),
        { target: { value: "Unsaved" } },
      );
      if (close === "cancel")
        fireEvent.click(screen.getByRole("button", { name: messages.cancel }));
      else fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(onSave).not.toHaveBeenCalled();
      view.rerender(
        <TemplateMetadataDialog
          {...props}
          template={{ name: "Current", description: "Current description" }}
        />,
      );
      open();
      expect(
        screen.getByRole<HTMLInputElement>("textbox", {
          name: messages.templateName,
        }).value,
      ).toBe("Current");
      expect(
        screen.getByRole<HTMLTextAreaElement>("textbox", {
          name: messages.templateDescription,
        }).value,
      ).toBe("Current description");
    },
  );

  it.each([false, true])(
    "labels layout controls and enforces built-in read-only state: %s",
    async (isBuiltIn) => {
      const base = getBuiltInTemplates(messages)[0];
      const onUpdateTemplate = vi.fn();
      const view = (avatarPosition: "left" | "none") => (
        <TemplateStyleTabs value="layout">
          <TemplateLayoutTab
            t={messages}
            template={{
              ...base,
              isBuiltIn,
              layout: { ...base.layout, avatarPosition },
            }}
            onUpdateTemplate={onUpdateTemplate}
          />
        </TemplateStyleTabs>
      );
      const result = render(view("left"));
      const labels = [
        messages.basicInfoLayout,
        messages.sectionTemplateStyle,
        messages.timelineItemLayout,
        messages.listItemLayout,
        messages.avatarPosition,
        messages.avatarSize,
        messages.templateDividerStyle,
      ];
      for (const label of labels) {
        const control = screen.getByRole<HTMLButtonElement>("combobox", {
          name: label,
        });
        expect(control.disabled).toBe(isBuiltIn);
      }
      expect(screen.getAllByRole("combobox")).toHaveLength(labels.length);
      const density = screen.getByRole("tablist", {
        name: messages.templateContentDensity,
      });
      for (const control of within(density).getAllByRole("tab")) {
        expect(control.getAttribute("aria-disabled") === "true").toBe(
          isBuiltIn,
        );
        if (isBuiltIn) {
          fireEvent.click(control);
          control.focus();
          fireEvent.keyDown(control, { key: "ArrowRight" });
        }
      }
      for (const control of screen.getAllByRole<HTMLInputElement>(
        "spinbutton",
      )) {
        expect(control.disabled).toBe(isBuiltIn);
      }
      const marginDetails = screen.getByRole<HTMLButtonElement>("button", {
        name: messages.pageMarginDetails,
      });
      expect(marginDetails.disabled).toBe(false);
      fireEvent.click(marginDetails);
      const dialog = screen.getByRole("dialog", { name: messages.pageMargin });
      for (const [label, value] of [
        [messages.pageMarginTop, base.settings.pagePaddingTop],
        [messages.pageMarginHorizontal, base.settings.pagePaddingX],
        [messages.pageMarginBottom, base.settings.pagePaddingBottom],
      ] as const) {
        const input = within(dialog).getByRole<HTMLInputElement>("spinbutton", {
          name: label,
        });
        expect(input.disabled).toBe(isBuiltIn);
        expect(Number(input.value)).toBe(value);
        if (isBuiltIn) fireEvent.change(input, { target: { value: "12" } });
      }
      const unify = within(dialog).queryByRole<HTMLButtonElement>("button", {
        name: messages.pageMarginUnify,
      });
      if (isBuiltIn) {
        expect(unify).toBeNull();
        expect(within(dialog).queryByText(messages.pageMarginHint)).toBeNull();
      } else {
        expect(unify).not.toBeNull();
      }
      fireEvent.keyDown(dialog, { key: "Escape" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).toBeNull();
        expect(document.activeElement).toBe(marginDetails);
      });
      result.rerender(view("none"));
      expect(
        screen.queryByRole("combobox", {
          name: messages.avatarSize,
        }),
      ).toBeNull();
      expect(onUpdateTemplate).not.toHaveBeenCalled();
    },
  );

  it("offers every avatar position and preserves the remaining layout when selected", () => {
    const template = { ...getBuiltInTemplates(messages)[0], isBuiltIn: false };
    const onUpdateTemplate = vi.fn();
    render(
      <TemplateStyleTabs value="layout">
        <TemplateLayoutTab
          t={messages}
          template={template}
          onUpdateTemplate={onUpdateTemplate}
        />
      </TemplateStyleTabs>,
    );
    fireEvent.keyDown(
      screen.getByRole("combobox", { name: messages.avatarPosition }),
      { key: "ArrowDown" },
    );
    expect(
      screen.getAllByRole("option").map((option) => option.textContent),
    ).toEqual([
      messages.avatarPositionNone,
      messages.avatarPositionLeft,
      messages.avatarPositionCenter,
      messages.avatarPositionRight,
    ]);
    fireEvent.click(
      screen.getByRole("option", { name: messages.avatarPositionCenter }),
    );
    expect(onUpdateTemplate).toHaveBeenCalledExactlyOnceWith({
      layout: { ...template.layout, avatarPosition: "center" },
    });
  });
});

it.each(["slider", "details"])(
  "preserves individual margins until an explicit adjustment through %s",
  (adjustment) => {
    const base = getBuiltInTemplates(en)[0];
    let template = {
      ...base,
      isBuiltIn: false,
      settings: {
        ...base.settings,
        pagePaddingTop: 19,
        pagePaddingX: 11,
        pagePaddingBottom: 9,
      },
    };
    const onUpdateTemplate = vi.fn(
      (patch: Partial<ResumeTemplateDefinition>) => {
        template = { ...template, ...patch };
        result.rerender(view());
      },
    );
    const view = () => (
      <TemplateStyleTabs value="layout">
        <TemplateLayoutTab
          t={en}
          template={template}
          onUpdateTemplate={onUpdateTemplate}
        />
      </TemplateStyleTabs>
    );
    const result = render(view());
    expect(onUpdateTemplate).not.toHaveBeenCalled();
    const details = screen.getByRole("button", {
      name: en.pageMarginDetails,
    });
    expect(details.textContent).toContain(en.templateCustomValue);
    const slider = screen.getByRole("slider", { name: en.pageMargin });
    expect(slider.getAttribute("aria-valuetext")).toBe(en.templateCustomValue);
    if (adjustment === "slider") {
      slider.focus();
      fireEvent.keyDown(slider, { key: "ArrowRight" });
      expect(onUpdateTemplate).toHaveBeenCalledOnce();
      expect(template.settings).toMatchObject({
        pagePaddingTop: 12,
        pagePaddingX: 12,
        pagePaddingBottom: 12,
      });
    } else {
      fireEvent.click(details);
      const dialog = screen.getByRole("dialog", { name: en.pageMargin });
      const labels = [
        en.pageMarginTop,
        en.pageMarginHorizontal,
        en.pageMarginBottom,
      ];
      const inputs = labels.map((label) =>
        within(dialog).getByRole<HTMLInputElement>("spinbutton", {
          name: label,
        }),
      );
      expect(inputs.map((input) => input.value)).toEqual(["19", "11", "9"]);
      inputs[0].focus();
      fireEvent.blur(inputs[0]);
      expect(onUpdateTemplate).not.toHaveBeenCalled();
      const expected = [19, 11, 9];
      for (const [index, value] of [14, 12, 13].entries()) {
        inputs[index].focus();
        fireEvent.change(inputs[index], { target: { value: String(value) } });
        expect(document.activeElement).toBe(inputs[index]);
        expected[index] = value;
        expect(inputs.map((input) => Number(input.value))).toEqual(expected);
        expect([
          template.settings.pagePaddingTop,
          template.settings.pagePaddingX,
          template.settings.pagePaddingBottom,
        ]).toEqual(expected);
      }
      expect(details.textContent).toContain(en.templateCustomValue);
      fireEvent.blur(inputs[2]);
      fireEvent.click(
        within(dialog).getByRole("button", { name: en.pageMarginUnify }),
      );
      expect(inputs.map((input) => input.value)).toEqual(["12", "12", "12"]);
      expect(
        within(dialog).getByRole<HTMLButtonElement>("button", {
          name: en.pageMarginUnify,
        }).disabled,
      ).toBe(true);
      expect(template.settings).toMatchObject({
        pagePaddingTop: 12,
        pagePaddingX: 12,
        pagePaddingBottom: 12,
      });
    }
    expect(details.textContent).toContain("12");
    expect(slider.getAttribute("aria-valuenow")).toBe("12");
    expect(template.settings.headingColor).toBe(base.settings.headingColor);
  },
);

it("applies density presets by click and keyboard without remounting custom spacing controls", async () => {
  const base = getBuiltInTemplates(en)[0];
  let template = {
    ...base,
    isBuiltIn: false,
    settings: {
      ...base.settings,
      sectionGap: 1.2,
      itemGap: 0.8,
      bodyLineHeight: 1.9,
    },
  };
  const onUpdateTemplate = vi.fn((patch: Partial<ResumeTemplateDefinition>) => {
    template = { ...template, ...patch };
    result.rerender(view());
  });
  const view = () => (
    <TemplateStyleTabs value="layout">
      <TemplateLayoutTab
        t={en}
        template={template}
        onUpdateTemplate={onUpdateTemplate}
      />
    </TemplateStyleTabs>
  );
  const result = render(view());
  const density = screen.getByRole("tablist", {
    name: en.templateContentDensity,
  });
  expect(
    screen.getByText(en.templatePageSpacing).closest("legend")?.textContent,
  ).toBe(en.templatePageSpacing);
  expect(within(density).queryByRole("tab", { selected: true })).toBeNull();
  expect(onUpdateTemplate).not.toHaveBeenCalled();
  const lineHeight = screen.getByRole<HTMLInputElement>("spinbutton", {
    name: en.lineSpacing,
  });
  const standard = within(density).getByRole("tab", {
    name: en.templatePresetStandard,
  });
  fireEvent.click(standard);
  expect(onUpdateTemplate).toHaveBeenCalledExactlyOnceWith({
    settings: {
      ...base.settings,
      sectionGap: 1.2,
      itemGap: 0.8,
      bodyLineHeight: 1.6,
    },
  });
  expect(standard.getAttribute("aria-selected")).toBe("true");
  lineHeight.focus();
  fireEvent.change(lineHeight, {
    target: {
      value: String(getResumeFontSizeInPoints(base.typography.fontSize) * 1.9),
    },
  });
  expect(template.settings.bodyLineHeight).toBe(1.9);
  expect(within(density).queryByRole("tab", { selected: true })).toBeNull();
  expect(screen.getByRole("spinbutton", { name: en.lineSpacing })).toBe(
    lineHeight,
  );
  expect(document.activeElement).toBe(lineHeight);
  standard.focus();
  fireEvent.keyDown(standard, { key: "ArrowRight" });
  const relaxed = within(density).getByRole("tab", {
    name: en.templatePresetRelaxed,
  });
  await waitFor(() => {
    expect(document.activeElement).toBe(relaxed);
    expect(relaxed.getAttribute("aria-selected")).toBe("true");
  });
  expect(onUpdateTemplate).toHaveBeenLastCalledWith({
    settings: {
      ...base.settings,
      sectionGap: 1.5,
      itemGap: 1,
      bodyLineHeight: 1.75,
    },
  });
  expect(screen.getByRole("spinbutton", { name: en.lineSpacing })).toBe(
    lineHeight,
  );
});

it("displays line spacing in points without rounding the stored ratio and saves point edits while focused", () => {
  const base = getBuiltInTemplates(en)[0];
  let template = {
    ...base,
    isBuiltIn: false,
    typography: { ...base.typography, fontSize: 16 },
    settings: { ...base.settings, bodyLineHeight: 1.46 },
  };
  const onUpdateTemplate = vi.fn((patch: Partial<ResumeTemplateDefinition>) => {
    template = { ...template, ...patch };
    result.rerender(view());
  });
  const view = () => (
    <TemplateStyleTabs value="layout">
      <TemplateLayoutTab
        t={en}
        template={template}
        onUpdateTemplate={onUpdateTemplate}
      />
    </TemplateStyleTabs>
  );
  const result = render(view());
  const input = screen.getByRole<HTMLInputElement>("spinbutton", {
    name: en.lineSpacing,
  });
  const slider = screen.getByRole("slider", { name: en.lineSpacing });
  expect(input.value).toBe("17.5");
  expect(slider.getAttribute("aria-valuetext")).toBe("17.5 pt");
  input.focus();
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.blur(input);
  expect(onUpdateTemplate).not.toHaveBeenCalled();
  expect(template.settings.bodyLineHeight).toBe(1.46);

  template = {
    ...template,
    typography: { ...template.typography, fontSize: 18 },
  };
  result.rerender(view());
  expect(input.value).toBe("19.7");
  expect(slider.getAttribute("aria-valuetext")).toBe("19.7 pt");
  expect(onUpdateTemplate).not.toHaveBeenCalled();

  input.focus();
  fireEvent.change(input, { target: { value: "20.3" } });
  expect(document.activeElement).toBe(input);
  expect(onUpdateTemplate).toHaveBeenCalledExactlyOnceWith({
    settings: { ...base.settings, bodyLineHeight: 1.5 },
  });
  fireEvent.blur(input);
  expect(input.value).toBe("20.3");
  expect(onUpdateTemplate).toHaveBeenCalledTimes(1);
  slider.focus();
  fireEvent.keyDown(slider, { key: "ArrowRight" });
  expect(template.settings.bodyLineHeight).toBe(1.55);
  expect(input.value).toBe("20.9");
  expect(template.typography.fontSize).toBe(18);
});

it("edits displayed point sizes without changing the persisted base size or unrelated scales", () => {
  const base = getBuiltInTemplates(en)[0];
  const template = { ...base, isBuiltIn: false };
  const onUpdateTemplate = vi.fn();
  render(
    <TemplateStyleTabs value="typography">
      <TemplateTypographyTab
        t={en}
        template={template}
        onUpdateTemplate={onUpdateTemplate}
      />
    </TemplateStyleTabs>,
  );
  const input = screen.getByRole<HTMLInputElement>("spinbutton", {
    name: en.nameSize,
  });
  const basePoints = getResumeFontSizeInPoints(template.typography.fontSize);
  expect(Number(input.value)).toBeCloseTo(
    basePoints * template.settings.nameScale,
    2,
  );
  input.focus();
  fireEvent.change(input, { target: { value: String(basePoints * 2.5) } });
  expect(document.activeElement).toBe(input);
  expect(onUpdateTemplate).toHaveBeenCalledExactlyOnceWith({
    settings: { ...template.settings, nameScale: 2.5 },
  });
});

it("validates hex edits and applies a palette without replacing other settings", () => {
  const base = getBuiltInTemplates(en)[0];
  const template = { ...base, isBuiltIn: false };
  const onUpdateTemplate = vi.fn();
  render(
    <TemplateStyleTabs value="visual">
      <TemplateVisualTab
        t={en}
        template={template}
        onUpdateTemplate={onUpdateTemplate}
      />
    </TemplateStyleTabs>,
  );
  const input = screen.getByRole<HTMLInputElement>("textbox", {
    name: `${en.headingColor} HEX`,
  });
  fireEvent.change(input, { target: { value: "invalid" } });
  fireEvent.blur(input);
  expect(onUpdateTemplate).not.toHaveBeenCalled();
  expect(input.value).toBe(template.settings.headingColor.toUpperCase());
  input.focus();
  fireEvent.change(input, { target: { value: "336699" } });
  expect(document.activeElement).toBe(input);
  expect(onUpdateTemplate).toHaveBeenCalledExactlyOnceWith({
    settings: { ...template.settings, headingColor: "#336699" },
  });
  fireEvent.click(screen.getByRole("radio", { name: en.templatePaletteBlue }));
  expect(onUpdateTemplate).toHaveBeenLastCalledWith({
    settings: {
      ...template.settings,
      pageBackground: "#ffffff",
      surfaceColor: "#f1f5fa",
      headingColor: "#334c70",
      bodyColor: "#27272a",
      mutedColor: "#7489a5",
      dividerColor: "#d9e2ee",
    },
  });
});

it.each(["typography", "visual"])(
  "keeps built-in %s controls read-only",
  (tab) => {
    const template = getBuiltInTemplates(en)[0];
    const onUpdateTemplate = vi.fn();
    render(
      <TemplateStyleTabs value={tab}>
        {tab === "typography" ? (
          <TemplateTypographyTab
            t={en}
            template={template}
            onUpdateTemplate={onUpdateTemplate}
          />
        ) : (
          <TemplateVisualTab
            t={en}
            template={template}
            onUpdateTemplate={onUpdateTemplate}
          />
        )}
      </TemplateStyleTabs>,
    );
    for (const role of ["combobox", "spinbutton", "textbox", "radio"]) {
      for (const control of screen.queryAllByRole<HTMLInputElement>(role))
        expect(control.disabled).toBe(true);
    }
    expect(onUpdateTemplate).not.toHaveBeenCalled();
  },
);

it("bounds committed numbers and lets users cancel incomplete edits", () => {
  const onChange = vi.fn();
  render(
    <TemplateNumberInput
      label="Margin"
      value={14}
      min={8}
      max={20}
      step={1}
      unit="mm"
      onChange={onChange}
    />,
  );
  const input = screen.getByRole<HTMLInputElement>("spinbutton", {
    name: "Margin",
  });
  fireEvent.change(input, { target: { value: "" } });
  fireEvent.blur(input);
  expect(input.value).toBe("14");
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "7" } });
  fireEvent.keyDown(input, { key: "Escape" });
  fireEvent.blur(input);
  expect(input.value).toBe("14");
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "25" } });
  fireEvent.blur(input);
  expect(onChange).toHaveBeenCalledExactlyOnceWith(20);
});
