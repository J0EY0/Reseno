import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { TemplateAvatarFields } from "@/components/templates/editor/avatar-fields";
import {
  getTemplateEditorMessages,
  type TemplateEditorMessages,
} from "@/components/templates/editor/editor-messages";
import enMessages from "@/i18n/locales/en.json";
import zhMessages from "@/i18n/locales/zh.json";
import { getBuiltInTemplates } from "@/lib/templates";
import type { ResumeTemplateDefinition } from "@/types/resume";

const en = getTemplateEditorMessages("en", enMessages);
const zh = getTemplateEditorMessages("zh", zhMessages);
const template = { ...getBuiltInTemplates(en)[0], isBuiltIn: false };

function AvatarEditor({
  t = en,
  initial = template,
  onChange,
}: {
  t?: TemplateEditorMessages;
  initial?: ResumeTemplateDefinition;
  onChange: (patch: Partial<ResumeTemplateDefinition["layout"]>) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <TemplateAvatarFields
      t={t}
      template={value}
      onChange={(patch) => {
        onChange(patch);
        setValue((current) => ({
          ...current,
          layout: { ...current.layout, ...patch },
        }));
      }}
    />
  );
}

function select(label: string, option: string) {
  fireEvent.keyDown(screen.getByRole("combobox", { name: label }), {
    key: "ArrowDown",
  });
  fireEvent.click(screen.getByRole("option", { name: option }));
}

it.each([en, zh])(
  "opens custom dimensions without changing the avatar, in $avatarSize",
  async (t) => {
    const onChange = vi.fn();
    render(<AvatarEditor t={t} onChange={onChange} />);
    select(t.avatarSize, t.templateCustomValue);
    const width = await screen.findByRole<HTMLInputElement>("spinbutton", {
      name: t.avatarWidth,
    });
    const height = screen.getByRole<HTMLInputElement>("spinbutton", {
      name: t.avatarHeight,
    });
    expect([width.value, height.value]).toEqual([
      String(template.layout.avatarWidth),
      String(template.layout.avatarHeight),
    ]);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(width, { target: { value: "33.5" } });
    expect(onChange).toHaveBeenLastCalledWith({ avatarWidth: 33.5 });
    fireEvent.change(height, { target: { value: "42" } });
    expect(onChange).toHaveBeenLastCalledWith({ avatarHeight: 42 });
    fireEvent.blur(width);
    fireEvent.blur(height);

    fireEvent.change(width, {
      target: { value: String(template.layout.avatarWidth) },
    });
    fireEvent.change(height, {
      target: { value: String(template.layout.avatarHeight) },
    });
    expect(
      screen.getByRole("combobox", { name: t.avatarSize }).textContent,
    ).toBe(t.templateCustomValue);
    expect(screen.getByRole("spinbutton", { name: t.avatarWidth })).toBe(width);

    select(t.avatarSize, t.avatarSizeStandard);
    expect(onChange).toHaveBeenLastCalledWith({
      avatarWidth: template.layout.avatarWidth,
      avatarHeight: template.layout.avatarHeight,
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("spinbutton", { name: t.avatarWidth }),
      ).toBeNull(),
    );
  },
);

it("loads custom dimensions and commits valid bounds without clearing values", async () => {
  const onChange = vi.fn();
  render(
    <AvatarEditor
      initial={{
        ...template,
        layout: { ...template.layout, avatarWidth: 33.5, avatarHeight: 42 },
      }}
      onChange={onChange}
    />,
  );
  const width = await screen.findByRole<HTMLInputElement>("spinbutton", {
    name: en.avatarWidth,
  });
  const height = screen.getByRole<HTMLInputElement>("spinbutton", {
    name: en.avatarHeight,
  });
  expect([width.value, height.value]).toEqual(["33.5", "42"]);
  fireEvent.change(width, { target: { value: "" } });
  fireEvent.blur(width);
  expect(width.value).toBe("33.5");
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(width, { target: { value: "99" } });
  fireEvent.keyDown(width, { key: "Enter" });
  expect(onChange).toHaveBeenLastCalledWith({ avatarWidth: 48 });
  fireEvent.change(height, { target: { value: "2" } });
  fireEvent.blur(height);
  expect(onChange).toHaveBeenLastCalledWith({ avatarHeight: 16 });
});

it("keeps custom dimensions read-only and hides them when the avatar is absent", async () => {
  const onChange = vi.fn();
  const custom = {
    ...template,
    isBuiltIn: true,
    layout: { ...template.layout, avatarWidth: 33.5, avatarHeight: 42 },
  };
  const view = (value: ResumeTemplateDefinition) => (
    <TemplateAvatarFields t={en} template={value} onChange={onChange} />
  );
  const { rerender } = render(view(custom));
  await screen.findByRole("spinbutton", { name: en.avatarWidth });
  expect(
    screen.getByRole<HTMLButtonElement>("combobox", {
      name: en.avatarSize,
    }).disabled,
  ).toBe(true);
  for (const label of [en.avatarWidth, en.avatarHeight]) {
    const input = screen.getByRole<HTMLInputElement>("spinbutton", {
      name: label,
    });
    expect(input.disabled).toBe(true);
    fireEvent.change(input, { target: { value: "40" } });
  }
  expect(onChange).not.toHaveBeenCalled();
  rerender(
    view({
      ...custom,
      layout: { ...custom.layout, avatarPosition: "none" },
    }),
  );
  expect(screen.queryByRole("combobox", { name: en.avatarSize })).toBeNull();
  await waitFor(() => expect(screen.queryByRole("spinbutton")).toBeNull());
});
