import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { InlineTextListInput } from "@/components/editor/inline-text-list-input";
import { defaultMessages as t } from "@/i18n";
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
it("keeps unfinished comma-separated typing after parent acknowledgement and adopts external values", async () => {
  const changes = vi.fn();
  function List() {
    const [value, setValue] = useState(["React"]);
    return (
      <>
        <InlineTextListInput
          t={t}
          aria-label="Technologies"
          value={value}
          onChange={(next) => {
            changes(next);
            setValue(next);
          }}
        />
        <button onClick={() => setValue(["Vue"])}>Replace externally</button>
      </>
    );
  }
  render(<List />);
  await act(() => vi.dynamicImportSettled());
  const input = await screen.findByRole("textbox", { name: "Technologies" });
  function paste(text: string) {
    act(() => input.focus());
    const selection = window.getSelection()!;
    const range = document.createRange();
    range.selectNodeContents(input);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
    fireEvent(document, new Event("selectionchange"));
    fireEvent.paste(input, {
      clipboardData: {
        getData: (type: string) => (type === "text/plain" ? text : ""),
        files: [],
      },
    });
  }
  paste(", ");
  await waitFor(() => expect(changes).toHaveBeenLastCalledWith(["React"]));
  expect(input.textContent).toBe("React, ");
  paste("TypeScript， Node");
  await waitFor(() =>
    expect(changes).toHaveBeenLastCalledWith(["React", "TypeScript", "Node"]),
  );
  expect(input.textContent).toBe("React, TypeScript， Node");
  const count = changes.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "Replace externally" }));
  await waitFor(() => expect(input.textContent).toBe("Vue"));
  expect(changes).toHaveBeenCalledTimes(count);
  paste(", ");
  await waitFor(() => expect(changes).toHaveBeenLastCalledWith(["Vue"]));
  expect(input.textContent).toBe("Vue, ");
});
