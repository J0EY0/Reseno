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
  vi.doUnmock("@/components/editor/resume-section-actions");
});

async function loadDelayedSectionCard() {
  vi.resetModules();
  const loading = vi.fn();
  const ready = Promise.withResolvers<void>();
  const loaded = Promise.withResolvers<unknown>();
  vi.doMock("@/components/editor/resume-section-content", async () => {
    loading();
    await ready.promise;
    const module = vi.importActual(
      "@/components/editor/resume-section-content",
    );
    loaded.resolve(module);
    return module;
  });
  const { ResumeSectionCard } =
    await import("@/components/editor/resume-section-card");
  return { ResumeSectionCard, loading, ready, loaded: loaded.promise };
}

it("loads only on expansion, keeps the card visible while loading and opens a new item only once", async () => {
  const { ResumeSectionCard, loading, ready, loaded } =
    await loadDelayedSectionCard();
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
  expect(
    screen.queryByRole("button", { name: en.addItem.education }),
  ).toBeNull();

  await act(async () => {
    ready.resolve();
    await loaded;
  });
  expect(
    await screen.findByRole("button", { name: en.addItem.education }),
  ).toBeTruthy();
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: en.addItem.education }));
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
    expect(
      screen.queryByRole("button", { name: en.addItem.education }),
    ).toBeNull(),
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

it("preserves an open delete confirmation when the section content finishes loading", async () => {
  const { ResumeSectionCard, loading, ready, loaded } =
    await loadDelayedSectionCard();
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
    `Education: ${en.moreActions}`,
  ];
  for (const name of actionLabels) {
    expect(screen.getAllByRole("button", { name })).toHaveLength(1);
  }
  expect(
    screen
      .getByRole("status", { name: "Loading" })
      .closest('[aria-busy="true"]'),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: en.addItem.education }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: actionLabels[2] }));
  expect(onMoveSectionUp).toHaveBeenCalledExactlyOnceWith(section.id);
  fireEvent.click(screen.getByRole("button", { name: actionLabels[3] }));
  expect(onMoveSectionDown).toHaveBeenCalledExactlyOnceWith(section.id);
  fireEvent.keyDown(screen.getByRole("button", { name: actionLabels[4] }), {
    key: "Enter",
  });
  fireEvent.click(
    await screen.findByRole("menuitem", { name: en.deleteSection }),
  );
  expect(await screen.findByRole("alertdialog")).toBeTruthy();

  await act(async () => {
    ready.resolve();
    await loaded;
  });
  await screen.findByText(en.addItem.education, { selector: "button" });
  const dialog = screen.getByRole("alertdialog");
  await waitFor(() =>
    expect(dialog.contains(document.activeElement)).toBe(true),
  );
  expect(dialog.isConnected).toBe(true);
  fireEvent.click(
    within(dialog).getByRole("button", { name: en.deleteSection }),
  );
  expect(onRemoveSection).toHaveBeenCalledExactlyOnceWith(section.id);
  expect(
    await screen.findByRole("button", { name: en.addItem.education }),
  ).toBeTruthy();
  expect(screen.queryByRole("status", { name: "Loading" })).toBeNull();
  for (const name of actionLabels) {
    expect(screen.getAllByRole("button", { name })).toHaveLength(1);
  }
  expect(
    screen.getAllByRole("button", { name: en.addItem.education }),
  ).toHaveLength(1);
});

it.each(["click", "Enter", " ", "ArrowDown"])(
  "opens a cold actions menu with one %s and restores trigger focus on Escape",
  async (activation) => {
    vi.resetModules();
    const actionsReady = Promise.withResolvers<void>();
    const loading = vi.fn();
    vi.doMock("@/components/editor/resume-section-actions", async () => {
      loading();
      await actionsReady.promise;
      return vi.importActual("@/components/editor/resume-section-actions");
    });
    const { ResumeSectionCard } =
      await import("@/components/editor/resume-section-card");
    const section = createResumeSection("education");
    section.title = "Education";
    render(
      <ResumeSectionCard
        t={en}
        documentT={en}
        section={section}
        collapsed
        onToggle={vi.fn()}
        onMutation={vi.fn()}
        canMoveUp={false}
        canMoveDown={false}
        onMoveSectionUp={vi.fn()}
        onMoveSectionDown={vi.fn()}
        onRemoveSection={vi.fn()}
      />,
    );
    expect(loading).not.toHaveBeenCalled();
    const trigger = screen.getByRole("button", {
      name: `Education: ${en.moreActions}`,
    });
    act(() => trigger.focus());
    await waitFor(() => expect(loading).toHaveBeenCalledOnce());
    expect(document.activeElement).toBe(trigger);
    if (activation === "click") fireEvent.click(trigger);
    else fireEvent.keyDown(trigger, { key: activation });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(
      screen.getByRole("button", {
        name: `Education: ${en.moreActions}`,
      }),
    );

    await act(async () => actionsReady.resolve());
    const firstItem = await screen.findByRole("menuitem", {
      name: en.renameSectionAction,
    });
    await waitFor(() => expect(document.activeElement).toBe(firstItem));
    fireEvent.keyDown(firstItem, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", {
          name: `Education: ${en.moreActions}`,
        }),
      ),
    );
  },
);

it.each(["Escape", "blur"])(
  "cancels a pending actions menu on %s without stealing focus when it loads",
  async (dismissal) => {
    vi.resetModules();
    const ready = Promise.withResolvers<void>();
    vi.doMock("@/components/editor/resume-section-actions", async () => {
      await ready.promise;
      return vi.importActual("@/components/editor/resume-section-actions");
    });
    const { ResumeSectionCard } =
      await import("@/components/editor/resume-section-card");
    const section = createResumeSection("education");
    section.title = "Education";
    render(
      <>
        <ResumeSectionCard
          t={en}
          documentT={en}
          section={section}
          collapsed
          onToggle={vi.fn()}
          onMutation={vi.fn()}
          canMoveUp={false}
          canMoveDown={false}
          onMoveSectionUp={vi.fn()}
          onMoveSectionDown={vi.fn()}
          onRemoveSection={vi.fn()}
        />
        <button type="button">Next control</button>
      </>,
    );
    const trigger = screen.getByRole("button", {
      name: `Education: ${en.moreActions}`,
    });
    act(() => trigger.focus());
    fireEvent.keyDown(trigger, { key: "Enter" });
    const focusTarget =
      dismissal === "blur"
        ? screen.getByRole("button", { name: "Next control" })
        : trigger;
    if (dismissal === "blur") act(() => focusTarget.focus());
    else fireEvent.keyDown(trigger, { key: "Escape" });
    await act(async () => ready.resolve());
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(focusTarget);
  },
);

it("keeps rename open and focused when the section content finishes loading", async () => {
  const { ResumeSectionCard, ready, loaded } = await loadDelayedSectionCard();
  const section = createResumeSection("education");
  section.title = "Education";
  render(
    <ResumeSectionCard
      t={en}
      documentT={en}
      section={section}
      collapsed={false}
      onToggle={vi.fn()}
      onMutation={vi.fn()}
      canMoveUp={false}
      canMoveDown={false}
      onMoveSectionUp={vi.fn()}
      onMoveSectionDown={vi.fn()}
      onRemoveSection={vi.fn()}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: `Education: ${en.moreActions}` }),
  );
  fireEvent.click(
    await screen.findByRole("menuitem", { name: en.renameSectionAction }),
  );
  expect(
    await screen.findByRole("dialog", {
      name: `Education: ${en.renameSectionAction}`,
    }),
  ).toBeTruthy();
  await act(async () => {
    ready.resolve();
    await loaded;
  });
  const nameField = await screen.findByRole("textbox", {
    name: en.renameSection,
  });
  await waitFor(() => expect(document.activeElement).toBe(nameField));
});
