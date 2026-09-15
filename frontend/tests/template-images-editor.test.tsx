import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { defaultMessages as t } from "@/i18n";
import { TemplateImagesTab } from "@/components/templates/editor/images-tab";
import { Tabs } from "@/components/ui/tabs";
import {
  createTemplateImageElement,
  getBuiltInTemplates,
} from "@/lib/templates";
import type { ResumeTemplateImageElement } from "@/types/resume";

const prepare = vi.hoisted(() => vi.fn());
vi.mock("@/lib/template-image-upload", () => ({
  prepareTemplateImage: prepare,
}));
const base = { ...getBuiltInTemplates(t)[0], id: "custom", isBuiltIn: false };
const makeImage = (index: number) => ({
  ...createTemplateImageElement(index, t.imageDefaultName, base.layout),
  id: `image-${index}`,
});

beforeEach(() => {
  prepare.mockReset().mockResolvedValue("data:image/png;base64,new-image");
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});
afterEach(() => vi.unstubAllGlobals());
function Editor({
  id = "custom",
  active = "images",
  initial = [makeImage(1)],
  isBuiltIn = false,
}: {
  id?: string;
  active?: string;
  initial?: ResumeTemplateImageElement[];
  isBuiltIn?: boolean;
}) {
  const [value, setValue] = useState({
    ...base,
    layout: { ...base.layout, images: initial },
  });
  return (
    <Tabs value={active}>
      <TemplateImagesTab
        t={t}
        template={{ ...value, id, isBuiltIn }}
        onUpdateTemplate={(patch) =>
          setValue((current) => ({
            ...current,
            ...(typeof patch === "function" ? patch(current) : patch),
          }))
        }
      />
    </Tabs>
  );
}
function card(index = 1) {
  return screen.getByRole("group", {
    name: `${t.templateImageControls} ${index}`,
  });
}
function expand(index = 1) {
  const group = card(index);
  fireEvent.click(
    group.querySelector<HTMLButtonElement>("button[aria-expanded]")!,
  );
  return group;
}
function upload(file: File, group = card()) {
  fireEvent.change(group.querySelector('input[type="file"]')!, {
    target: { files: [file] },
  });
}

it("adds a uniquely named image, expands only that image, and remembers expansion across tabs and templates", () => {
  const view = render(<Editor />);
  const original = card();
  expect(original.querySelector('input[type="file"]')).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: t.addTemplateImage }));
  const added = card(2);
  expect(within(added).getByText(`${t.imageDefaultName} 2`)).not.toBeNull();
  expect(added.querySelector('input[type="file"]')).not.toBeNull();
  expect(original.querySelector('input[type="file"]')).toBeNull();
  view.rerender(<Editor active="layout" />);
  expect(
    screen.queryByRole("group", { name: `${t.templateImageControls} 2` }),
  ).toBeNull();
  view.rerender(<Editor />);
  expect(card(2).querySelector('input[type="file"]')).not.toBeNull();
  view.rerender(<Editor id="another-template" />);
  expect(card(2).querySelector('input[type="file"]')).toBeNull();
  expand(1);
  view.rerender(<Editor />);
  expect(card(2).querySelector('input[type="file"]')).not.toBeNull();
  expect(card(1).querySelector('input[type="file"]')).toBeNull();
});
it.each(["Enter", "Escape"])(
  "commits or discards an image name through %s",
  (key) => {
    render(<Editor />);
    fireEvent.click(
      within(card()).getByRole("button", { name: t.editImageName }),
    );
    const input = screen.getByRole("textbox", { name: t.imageName });
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: "Updated image" } });
    fireEvent.keyDown(input, { key });
    expect(screen.queryByRole("textbox", { name: t.imageName })).toBeNull();
    expect(
      within(card()).getByText(
        key === "Enter" ? "Updated image" : `${t.imageDefaultName} 1`,
      ),
    ).not.toBeNull();
  },
);
it("uploads and replaces the source, adopts the file basename, and resets the input for reselection", async () => {
  render(<Editor />);
  const group = expand();
  const file = new File(["first"], "portrait.original.png", {
    type: "image/png",
  });
  const input = group.querySelector<HTMLInputElement>('input[type="file"]')!;
  const click = vi.spyOn(input, "click");
  fireEvent.click(within(group).getByRole("button", { name: t.uploadImage }));
  expect(click).toHaveBeenCalledOnce();
  upload(file, group);
  await waitFor(() =>
    expect(within(group).getByRole("img").getAttribute("src")).toBe(
      "data:image/png;base64,new-image",
    ),
  );
  expect(prepare).toHaveBeenCalledExactlyOnceWith(file);
  expect(within(group).getByText("portrait.original")).not.toBeNull();
  expect(within(group).getByRole("img").getAttribute("alt")).toBe(file.name);
  expect(input.value).toBe("");
  expect(
    within(group).getByRole("button", { name: t.replaceImage }),
  ).not.toBeNull();
  prepare.mockResolvedValue("data:image/png;base64,replaced-image");
  upload(file, group);
  await waitFor(() =>
    expect(within(group).getByRole("img").getAttribute("src")).toBe(
      "data:image/png;base64,replaced-image",
    ),
  );
  expect(prepare).toHaveBeenCalledTimes(2);
});
it("preserves a user rename made while an upload is being prepared", async () => {
  const uploaded = Promise.withResolvers<string>();
  prepare.mockReturnValue(uploaded.promise);
  render(<Editor />);
  const group = expand();
  upload(new File(["photo"], "file-name.png", { type: "image/png" }), group);
  await waitFor(() => expect(prepare).toHaveBeenCalledOnce());
  fireEvent.click(within(group).getByRole("button", { name: t.editImageName }));
  const name = screen.getByRole("textbox", { name: t.imageName });
  fireEvent.change(name, { target: { value: "Chosen by user" } });
  fireEvent.keyDown(name, { key: "Enter" });
  await act(async () => uploaded.resolve("data:image/png;base64,ready"));
  expect(within(group).getByText("Chosen by user")).not.toBeNull();
  expect(within(group).getByRole("img").getAttribute("src")).toBe(
    "data:image/png;base64,ready",
  );
});
it("updates all eight image controls and the fit through their actual inputs", () => {
  render(<Editor />);
  const group = expand();
  for (const [label, value] of [
    [t.imagePositionX, 20],
    [t.imagePositionY, 30],
    [t.imageWidth, 40],
    [t.imageHeight, 50],
    [t.imageOpacity, 75],
    [t.imageBorderRadius, 12],
    [t.imageBorderWidth, 2],
  ] as const) {
    const input = within(group).getByRole<HTMLInputElement>("spinbutton", {
      name: label,
    });
    fireEvent.change(input, { target: { value: String(value) } });
    fireEvent.blur(input);
    expect(input.value).toBe(String(value));
  }
  const color = within(group).getByLabelText<HTMLInputElement>(
    t.imageBorderColor,
  );
  fireEvent.change(color, { target: { value: "#123456" } });
  expect(color.value).toBe("#123456");
  expect(
    group.querySelector<HTMLElement>('[data-slot="template-image-thumbnail"]')
      ?.style.borderColor,
  ).toBe("rgb(18, 52, 86)");
  fireEvent.keyDown(
    within(group).getByRole("combobox", { name: t.imageFitLabel }),
    { key: "ArrowDown" },
  );
  fireEvent.click(screen.getByRole("option", { name: t.imageFitCover }));
  expect(
    within(group).getByRole("combobox", { name: t.imageFitLabel }).textContent,
  ).toContain(t.imageFitCover);
});
it("keeps builtin image controls read-only and allows removing an editable image", () => {
  const view = render(<Editor isBuiltIn />);
  const group = expand();
  for (const label of [
    t.addTemplateImage,
    t.editImageName,
    t.removeImage,
    t.uploadImage,
  ])
    expect(
      (screen.getByRole("button", { name: label }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  for (const input of group.querySelectorAll<HTMLInputElement>("input"))
    expect(input.disabled).toBe(true);
  expect(
    (
      within(group).getByRole("combobox", {
        name: t.imageFitLabel,
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(prepare).not.toHaveBeenCalled();
  view.rerender(<Editor />);
  fireEvent.click(within(card()).getByRole("button", { name: t.removeImage }));
  expect(
    screen.queryByRole("group", { name: `${t.templateImageControls} 1` }),
  ).toBeNull();
});
