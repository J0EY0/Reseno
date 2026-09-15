import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import type { BasicInfoFieldsProps } from "@/components/editor/basic-info-fields";
import en from "@/i18n/locales/en.json";
import { createEmptyResume } from "@/lib/resume";

afterEach(() => {
  vi.doUnmock("@/components/editor/basic-info-fields");
});

it("loads fields on expansion while preserving the header, then accepts contact edits", async () => {
  vi.resetModules();
  const loading = vi.fn();
  const ready = Promise.withResolvers<void>();
  vi.doMock("@/components/editor/basic-info-fields", async () => {
    loading();
    await ready.promise;
    return vi.importActual("@/components/editor/basic-info-fields");
  });
  const { BasicInfoCard } = await import("@/components/editor/basic-info-card");
  const props: BasicInfoFieldsProps = {
    t: en,
    basic: createEmptyResume().basic,
    onUpdateBasic: vi.fn(),
    onUpdateCustomField: vi.fn(),
    onAddCustomField: vi.fn(),
    onRemoveCustomField: vi.fn(),
    onAvatarUpload: vi.fn(),
    onRemoveAvatar: vi.fn(),
  };

  function Editor() {
    const [collapsed, setCollapsed] = useState(true);
    return (
      <BasicInfoCard
        {...props}
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
      />
    );
  }

  render(<Editor />);
  const header = screen.getByRole("heading", { name: en.basicInfo });
  const toggle = screen.getByRole("button", {
    name: `${en.basicInfo}: ${en.toggleSection}`,
  });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(loading).not.toHaveBeenCalled();
  fireEvent.click(toggle);
  await waitFor(() => expect(loading).toHaveBeenCalledOnce());
  expect(screen.getByRole("heading", { name: en.basicInfo })).toBe(header);
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByLabelText(en.fieldLabels.phone)).toBeNull();

  await act(async () => ready.resolve());
  for (const [field, value] of [
    ["phone", "+1 202 555 0123"],
    ["email", "editor@example.com"],
  ] as const) {
    const input = await screen.findByRole("textbox", {
      name: en.fieldLabels[field],
    });
    fireEvent.change(input, { target: { value } });
    expect(props.onUpdateBasic).toHaveBeenLastCalledWith(field, value);
  }
  expect(props.onUpdateBasic).toHaveBeenCalledTimes(2);
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(screen.getAllByRole("heading", { name: en.basicInfo })).toHaveLength(
    1,
  );
  expect(loading).toHaveBeenCalledOnce();
});
