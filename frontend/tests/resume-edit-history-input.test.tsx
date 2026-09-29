import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { Editor } from "@tiptap/react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import InlineTextEditor from "@/components/editor/inline-text-editor";
import { ResumeEditHistoryProvider } from "@/components/editor/resume-edit-history-provider";
import { ResumeSectionNameField } from "@/components/editor/resume-section-content";
import { RichHighlightsEditor } from "@/components/editor/rich-highlights-editor";
import { Popover, PopoverContent } from "@/components/ui/popover";
import { defaultMessages as t } from "@/i18n";
import { createResumeSection } from "@/lib/resume-sections";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restore: () => void;
const rangeDescriptors = new Map<string, PropertyDescriptor | undefined>();

beforeEach(() => {
  restore = installPanelBrowserApis();
  for (const [name, value] of [
    ["getClientRects", () => []],
    ["getBoundingClientRect", () => new DOMRect()],
  ] as const) {
    rangeDescriptors.set(
      name,
      Object.getOwnPropertyDescriptor(Range.prototype, name),
    );
    Object.defineProperty(Range.prototype, name, { configurable: true, value });
  }
});

afterEach(() => {
  restore();
  vi.unstubAllGlobals();
  for (const [name, descriptor] of rangeDescriptors) {
    if (descriptor) Object.defineProperty(Range.prototype, name, descriptor);
    else Reflect.deleteProperty(Range.prototype, name);
  }
});

it("routes field shortcuts and browser undo to document history without capturing other inputs", () => {
  const history = {
    canUndo: true,
    canRedo: true,
    undo: vi.fn(),
    redo: vi.fn(),
  };
  const localKeyDown = vi.fn();
  const breakGroup = vi.fn();
  const { rerender } = render(
    <>
      <ResumeEditHistoryProvider
        value={history}
        onBreakHistoryGroup={breakGroup}
      >
        <input aria-label="Resume email" onKeyDown={localKeyDown} />
        <div inert>
          <input aria-label="Unavailable field" />
        </div>
        {createPortal(<input aria-label="Dialog draft" />, document.body)}
      </ResumeEditHistoryProvider>
      <textarea aria-label="Agent prompt" />
    </>,
  );
  const input = screen.getByRole("textbox", { name: "Resume email" });
  act(() => input.focus());
  expect(breakGroup).toHaveBeenCalledOnce();
  expect(fireEvent.keyDown(input, { key: "z", metaKey: true })).toBe(false);
  expect(history.undo).toHaveBeenCalledOnce();
  expect(localKeyDown).not.toHaveBeenCalled();
  expect(
    fireEvent.keyDown(input, { key: "Z", ctrlKey: true, shiftKey: true }),
  ).toBe(false);
  expect(fireEvent.keyDown(input, { key: "y", ctrlKey: true })).toBe(false);
  expect(history.redo).toHaveBeenCalledTimes(2);

  for (const inputType of ["historyUndo", "historyRedo"]) {
    expect(
      fireEvent(
        input,
        new InputEvent("beforeinput", {
          inputType,
          bubbles: true,
          cancelable: true,
        }),
      ),
    ).toBe(false);
  }
  expect(history.undo).toHaveBeenCalledTimes(2);
  expect(history.redo).toHaveBeenCalledTimes(3);

  for (const label of ["Agent prompt", "Dialog draft", "Unavailable field"]) {
    expect(
      fireEvent.keyDown(screen.getByLabelText(label), {
        key: "z",
        metaKey: true,
      }),
    ).toBe(true);
  }
  expect(
    fireEvent.keyDown(input, { key: "z", metaKey: true, isComposing: true }),
  ).toBe(true);
  expect(history.undo).toHaveBeenCalledTimes(2);

  rerender(
    <ResumeEditHistoryProvider
      value={{ ...history, canUndo: false, canRedo: false }}
    >
      <input aria-label="Resume email" />
    </ResumeEditHistoryProvider>,
  );
  const emptyHistoryInput = screen.getByLabelText("Resume email");
  expect(
    fireEvent.keyDown(emptyHistoryInput, { key: "z", metaKey: true }),
  ).toBe(false);
  expect(
    fireEvent(
      emptyHistoryInput,
      new InputEvent("beforeinput", {
        inputType: "historyUndo",
        bubbles: true,
        cancelable: true,
      }),
    ),
  ).toBe(false);
  expect(history.undo).toHaveBeenCalledTimes(2);
});

it.each(["keyboard", "beforeinput"])(
  "routes live section rename %s undo and redo through document history once",
  (kind) => {
    const history = {
      canUndo: true,
      canRedo: true,
      undo: vi.fn(),
      redo: vi.fn(),
    };
    const onMutation = vi.fn();
    const breakGroup = vi.fn();
    const section = createResumeSection("experience");
    render(
      <ResumeEditHistoryProvider
        value={history}
        onBreakHistoryGroup={breakGroup}
      >
        <Popover open>
          <PopoverContent>
            <ResumeSectionNameField
              t={t}
              section={section}
              onMutation={onMutation}
            />
          </PopoverContent>
        </Popover>
      </ResumeEditHistoryProvider>,
    );
    const input = screen.getByRole("textbox", { name: t.renameSection });
    expect(document.activeElement).toBe(input);
    expect(breakGroup).toHaveBeenCalledOnce();
    breakGroup.mockClear();
    for (const title of ["Updated section", "Updated section title"]) {
      fireEvent.change(input, { target: { value: title } });
      expect(onMutation).toHaveBeenLastCalledWith({
        type: "section.rename",
        sectionId: section.id,
        title,
      });
    }
    expect(onMutation).toHaveBeenCalledTimes(2);
    expect(breakGroup).not.toHaveBeenCalled();

    if (kind === "keyboard") {
      expect(fireEvent.keyDown(input, { key: "z", metaKey: true })).toBe(false);
      expect(
        fireEvent.keyDown(input, { key: "z", metaKey: true, shiftKey: true }),
      ).toBe(false);
    } else {
      for (const inputType of ["historyUndo", "historyRedo"]) {
        expect(
          fireEvent(
            input,
            new InputEvent("beforeinput", {
              inputType,
              bubbles: true,
              cancelable: true,
            }),
          ),
        ).toBe(false);
      }
    }
    expect(history.undo).toHaveBeenCalledOnce();
    expect(history.redo).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(input);
    expect(onMutation).toHaveBeenCalledTimes(2);
  },
);

it.each([
  {
    kind: "inline",
    position: 5,
    updated: "Orig changedinal content",
    restoredPosition: 13,
  },
  {
    kind: "highlights",
    position: 5,
    updated: "Orig changedinal content",
    restoredPosition: 13,
  },
  {
    kind: "inline",
    position: 17,
    updated: "Original content changed",
    restoredPosition: 17,
  },
  {
    kind: "highlights",
    position: 17,
    updated: "Original content changed",
    restoredPosition: 17,
  },
])(
  "keeps $kind editing in document history and restores selection after undo at $position",
  async ({ kind, position, updated, restoredPosition }) => {
    const changes = vi.fn();
    const undo = vi.fn();
    const redo = vi.fn();
    function Editable() {
      const [value, setValue] = useState("Original content");
      const [previous, setPrevious] = useState<string | null>(null);
      const [next, setNext] = useState<string | null>(null);
      const onChange = (updated: string) => {
        changes(updated);
        setPrevious(value);
        setNext(null);
        setValue(updated);
      };
      return (
        <ResumeEditHistoryProvider
          value={{
            canUndo: previous !== null,
            canRedo: next !== null,
            undo() {
              undo();
              setNext(value);
              setValue(previous!);
              setPrevious(null);
            },
            redo() {
              redo();
              setPrevious(value);
              setValue(next!);
              setNext(null);
            },
          }}
        >
          {kind === "inline" ? (
            <InlineTextEditor
              t={t}
              aria-label="Content"
              value={value}
              onChange={onChange}
            />
          ) : (
            <RichHighlightsEditor
              t={t}
              label="Content"
              placeholder="Write content"
              value={[value]}
              onChange={onChange}
            />
          )}
        </ResumeEditHistoryProvider>
      );
    }
    render(<Editable />);
    const input = await screen.findByRole("textbox", { name: "Content" });
    const editor = (input as HTMLElement & { editor: Editor }).editor;
    act(() => {
      input.focus();
      editor.commands.setTextSelection(position);
      editor.commands.insertContent(" changed");
    });
    await waitFor(() => expect(changes).toHaveBeenCalledOnce());
    expect(input.textContent).toBe(updated);
    expect(editor.state.selection.anchor).toBe(position + 8);
    expect(fireEvent.keyDown(input, { key: "z", metaKey: true })).toBe(false);
    await waitFor(() => expect(input.textContent).toBe("Original content"));
    expect(undo).toHaveBeenCalledOnce();
    expect(changes).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(input);
    expect(editor.state.selection.anchor).toBe(restoredPosition);
    expect(
      fireEvent.keyDown(input, { key: "z", metaKey: true, shiftKey: true }),
    ).toBe(false);
    await waitFor(() => expect(input.textContent).toBe(updated));
    expect(redo).toHaveBeenCalledOnce();
    expect(changes).toHaveBeenCalledOnce();

    if (kind === "highlights") {
      fireEvent.click(
        screen.getByRole("button", { name: t.richTextMoreFormatting }),
      );
      fireEvent.click(screen.getByRole("button", { name: t.richTextUndo }));
      await waitFor(() => expect(input.textContent).toBe("Original content"));
      expect(undo).toHaveBeenCalledTimes(2);
      fireEvent.click(screen.getByRole("button", { name: t.richTextRedo }));
      await waitFor(() => expect(input.textContent).toBe(updated));
      expect(redo).toHaveBeenCalledTimes(2);
    }
  },
);
