import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { getTemplateEditorMessages } from "@/components/templates/editor/editor-messages";
import { TemplateTimelineLayoutFields } from "@/components/templates/editor/timeline-layout-fields";
import { defaultMessages } from "@/i18n";
import zhMessages from "@/i18n/locales/zh.json";
import { createTemplateLayout } from "@/lib/templates";
import type { ResumeTemplateLayout } from "@/types/resume";

const en = getTemplateEditorMessages("en", defaultMessages);
const zh = getTemplateEditorMessages("zh", zhMessages);

function Editor({
  t = en,
  initial = createTemplateLayout("minimal"),
  disabled = false,
  onChange = vi.fn(),
}: {
  t?: typeof en;
  initial?: ResumeTemplateLayout;
  disabled?: boolean;
  onChange?: (patch: Partial<ResumeTemplateLayout>) => void;
}) {
  const [layout, setLayout] = useState(initial);
  return (
    <TemplateTimelineLayoutFields
      t={t}
      layout={layout}
      disabled={disabled}
      onChange={(patch) => {
        onChange(patch);
        setLayout((current) => ({ ...current, ...patch }));
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
  "keeps section choices independent and restores global inheritance in $sectionItemLayouts",
  async (t) => {
    const onChange = vi.fn();
    render(<Editor t={t} onChange={onChange} />);
    expect(
      screen.queryByRole("combobox", { name: t.sectionTitles.education }),
    ).toBeNull();
    select(t.timelineItemLayout, t.timelineItemLayoutInline);
    expect(onChange).toHaveBeenLastCalledWith({ timelineItemLayout: "inline" });
    fireEvent.click(screen.getByRole("button", { name: t.sectionItemLayouts }));
    await screen.findByRole("combobox", { name: t.sectionTitles.education });
    select(t.sectionTitles.education, t.timelineItemLayoutInline);
    select(t.sectionTitles.experience, t.timelineItemLayoutStacked);
    select(t.timelineItemLayout, t.timelineItemLayoutCompact);
    expect(
      screen.getByRole("combobox", { name: t.sectionTitles.education })
        .textContent,
    ).toBe(t.timelineItemLayoutInline);
    expect(
      screen.getByRole("combobox", { name: t.sectionTitles.experience })
        .textContent,
    ).toBe(t.timelineItemLayoutStacked);
    expect(
      screen.getByRole("combobox", { name: t.sectionTitles.project })
        .textContent,
    ).toBe(t.sectionItemLayoutInherit);
    select(t.sectionTitles.education, t.sectionItemLayoutInherit);
    expect(onChange).toHaveBeenLastCalledWith({
      sectionItemLayouts: { experience: "stacked" },
    });
    const inherited = screen.getByRole("combobox", {
      name: t.sectionTitles.education,
    });
    expect(inherited.textContent).toBe(t.sectionItemLayoutInherit);
    const preview = 'span[aria-hidden="true"] > svg';
    expect(inherited.querySelector(preview)?.outerHTML).toBe(
      screen
        .getByRole("combobox", { name: t.timelineItemLayout })
        .querySelector(preview)?.outerHTML,
    );
    expect(
      screen.queryByRole("combobox", { name: t.sectionTitles.simple_list }),
    ).toBeNull();
  },
);

it("exposes saved overrides without allowing built-in layout changes", async () => {
  const onChange = vi.fn();
  render(
    <Editor
      disabled
      onChange={onChange}
      initial={createTemplateLayout("minimal", {
        sectionItemLayouts: { education: "inline", project: "compact" },
      })}
    />,
  );
  const toggle = screen.getByRole("button", { name: en.sectionItemLayouts });
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(toggle.textContent).toContain("2");
  await screen.findByRole("combobox", { name: en.sectionTitles.education });
  for (const control of screen.getAllByRole<HTMLButtonElement>("combobox"))
    expect(control.disabled).toBe(true);
  expect(
    within(
      screen.getByRole("combobox", { name: en.sectionTitles.education }),
    ).getByText(en.timelineItemLayoutInline),
  ).not.toBeNull();
  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(onChange).not.toHaveBeenCalled();
});
