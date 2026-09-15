import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TemplateColorField,
  TemplateSliderField,
} from "@/components/templates/editor/editor-fields";
import { TemplateLayoutTab } from "@/components/templates/editor/layout-tab";
import { TemplateMetadataDialog } from "@/components/templates/template-metadata-dialog";
import { Tabs } from "@/components/ui/tabs";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";
import { getBuiltInTemplates } from "@/lib/templates";

afterEach(() => vi.unstubAllGlobals());

it("associates color and slider labels with the actual controls", () => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
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
        displayValue="50%"
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
    (isBuiltIn) => {
      const base = getBuiltInTemplates(messages)[0];
      const onUpdateTemplate = vi.fn();
      const view = (avatarPosition: "left" | "none") => (
        <Tabs value="layout">
          <TemplateLayoutTab
            t={messages}
            template={{
              ...base,
              isBuiltIn,
              layout: { ...base.layout, avatarPosition },
            }}
            onUpdateTemplate={onUpdateTemplate}
          />
        </Tabs>
      );
      const result = render(view("left"));
      const labels = [
        messages.basicInfoLayout,
        messages.sectionTemplateStyle,
        messages.timelineItemLayout,
        messages.listItemLayout,
        messages.avatarPosition,
        messages.avatarSize,
        messages.pageMargin,
        messages.templateContentDensity,
        messages.templateDividerStyle,
      ];
      for (const label of labels) {
        const control = screen.getByRole<HTMLButtonElement>("combobox", {
          name: label,
        });
        expect(control.disabled).toBe(isBuiltIn);
      }
      expect(screen.getAllByRole("combobox")).toHaveLength(labels.length);
      result.rerender(view("none"));
      expect(
        screen.queryByRole("combobox", {
          name: messages.avatarSize,
        }),
      ).toBeNull();
      expect(onUpdateTemplate).not.toHaveBeenCalled();
    },
  );
});
