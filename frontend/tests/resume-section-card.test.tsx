import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import en from "@/i18n/locales/en.json";
import { applySectionMutation } from "@/lib/resume-section-mutations";
import { createResumeSection } from "@/lib/resume-sections";

vi.mock("@/components/workspace/workspace-preferences-context", () => ({
  useWorkspacePreferences: () => ({ locale: "en" }),
}));

afterEach(() => {
  vi.doUnmock("@/components/editor/resume-section-content");
});

async function loadDelayedSectionCard() {
  vi.resetModules();
  const loading = vi.fn();
  const ready = Promise.withResolvers<void>();
  vi.doMock("@/components/editor/resume-section-content", async () => {
    loading();
    await ready.promise;
    return vi.importActual("@/components/editor/resume-section-content");
  });
  const { ResumeSectionCard } =
    await import("@/components/editor/resume-section-card");
  return { ResumeSectionCard, loading, ready };
}

it("loads only on expansion, keeps the card visible while loading and opens a new item only once", async () => {
  const { ResumeSectionCard, loading, ready } = await loadDelayedSectionCard();
  const initialSection = createResumeSection("education");
  initialSection.title = "Education";
  initialSection.items = [];

  function Editor() {
    const [section, setSection] = useState(initialSection);
    const [collapsed, setCollapsed] = useState(true);
    return (
      <ResumeSectionCard
        t={en}
        documentT={en}
        section={section}
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
        onMutation={(mutation) =>
          setSection(
            (current) => applySectionMutation([current], mutation).sections[0],
          )
        }
        canMoveUp={false}
        canMoveDown={false}
        onMoveSectionUp={vi.fn()}
        onMoveSectionDown={vi.fn()}
        onRemoveSection={vi.fn()}
      />
    );
  }

  render(<Editor />);
  const toggle = screen.getByRole("button", {
    name: `Education: ${en.toggleSection}`,
  });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(loading).not.toHaveBeenCalled();
  fireEvent.click(toggle);
  await waitFor(() => expect(loading).toHaveBeenCalledOnce());
  expect(screen.getByRole("button", { name: "Education" })).toBeTruthy();
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByLabelText(en.renameSection)).toBeNull();

  await act(async () => ready.resolve());
  expect(await screen.findByLabelText(en.renameSection)).toBeTruthy();
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: en.addItem }));
  const itemToggle = await screen.findByRole("button", {
    name: `${en.toggleItem} 1`,
  });
  expect(itemToggle.getAttribute("aria-expanded")).toBe("true");
  const school = await screen.findByRole("textbox", {
    name: en.fieldLabels.school,
  });
  await waitFor(() => expect(document.activeElement).toBe(school));
  expect(
    screen.getByRole("button", { name: "Education" }).textContent,
  ).toContain(`1 ${en.itemCountSingular}`);

  fireEvent.click(toggle);
  await waitFor(() =>
    expect(screen.queryByLabelText(en.renameSection)).toBeNull(),
  );
  fireEvent.click(toggle);
  const reopenedItem = await screen.findByRole("button", {
    name: `${en.toggleItem} 1`,
  });
  expect(reopenedItem.getAttribute("aria-expanded")).toBe("false");
  expect(
    screen.queryByRole("textbox", { name: en.fieldLabels.school }),
  ).toBeNull();
  expect(loading).toHaveBeenCalledOnce();
});

it("shows a newly expanded card and its actions while the content loads", async () => {
  const { ResumeSectionCard, loading, ready } = await loadDelayedSectionCard();
  const section = createResumeSection("education");
  section.title = "Education";
  section.items = [];
  const onMoveSectionUp = vi.fn();
  const onMoveSectionDown = vi.fn();
  const onRemoveSection = vi.fn();
  render(
    <ResumeSectionCard
      t={en}
      documentT={en}
      section={section}
      collapsed={false}
      onToggle={vi.fn()}
      onMutation={vi.fn()}
      canMoveUp
      canMoveDown
      onMoveSectionUp={onMoveSectionUp}
      onMoveSectionDown={onMoveSectionDown}
      onRemoveSection={onRemoveSection}
    />,
  );
  await waitFor(() => expect(loading).toHaveBeenCalledOnce());
  const actionLabels = [
    "Education",
    `Education: ${en.toggleSection}`,
    `Education: ${en.moveSectionUp}`,
    `Education: ${en.moveSectionDown}`,
    `Education: ${en.deleteSection}`,
  ];
  for (const name of actionLabels) {
    expect(screen.getAllByRole("button", { name })).toHaveLength(1);
  }
  expect(
    screen
      .getByRole("status", { name: "Loading" })
      .closest('[aria-busy="true"]'),
  ).toBeTruthy();
  expect(screen.queryByLabelText(en.renameSection)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: actionLabels[2] }));
  expect(onMoveSectionUp).toHaveBeenCalledExactlyOnceWith(section.id);
  fireEvent.click(screen.getByRole("button", { name: actionLabels[3] }));
  expect(onMoveSectionDown).toHaveBeenCalledExactlyOnceWith(section.id);
  fireEvent.click(screen.getByRole("button", { name: actionLabels[4] }));
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(
    within(dialog).getByRole("button", { name: en.deleteSection }),
  );
  expect(onRemoveSection).toHaveBeenCalledExactlyOnceWith(section.id);

  await act(async () => ready.resolve());
  expect(await screen.findByLabelText(en.renameSection)).toBeTruthy();
  expect(screen.queryByRole("status", { name: "Loading" })).toBeNull();
  for (const name of actionLabels) {
    expect(screen.getAllByRole("button", { name })).toHaveLength(1);
  }
  expect(screen.getAllByRole("button", { name: en.addItem })).toHaveLength(1);
});
