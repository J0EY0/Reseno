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
import { defaultMessages } from "@/i18n";
import { getTemplateEditorMessages } from "@/components/templates/editor/editor-messages";
import { TemplateImagesTab } from "@/components/templates/editor/images-tab";
import {
  TemplateStyleTabs,
  TemplateStyleTabsContent,
} from "@/components/templates/template-style-tabs";
import {
  createTemplateImageElement,
  getBuiltInTemplates,
} from "@/lib/templates";
import type { ResumeTemplateImageElement } from "@/types/resume";

const t = getTemplateEditorMessages("en", defaultMessages);

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
    <TemplateStyleTabs value={active}>
      <TemplateStyleTabsContent value="images" keepMounted>
        <TemplateImagesTab
          t={t}
          locale="en"
          template={{ ...value, id, isBuiltIn }}
          onUpdateTemplate={(patch) =>
            setValue((current) => ({
              ...current,
              ...(typeof patch === "function" ? patch(current) : patch),
            }))
          }
        />
      </TemplateStyleTabsContent>
    </TemplateStyleTabs>
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
    within(group).getByRole("button", { name: t.expandImageSettings }),
  );
  return group;
}
function action(label: string, group = card()) {
  fireEvent.keyDown(
    within(group).getByRole("button", { name: t.moreActions }),
    { key: "Enter" },
  );
  fireEvent.click(screen.getByRole("menuitem", { name: label }));
}
function upload(file: File, group = card()) {
  fireEvent.change(group.querySelector('input[type="file"]')!, {
    target: { files: [file] },
  });
}

it("adds a uniquely named image, expands only that image, and remembers expansion across tabs and templates", () => {
  const view = render(<Editor />);
  const original = card();
  expect(
    within(original).queryByRole("spinbutton", { name: t.imagePositionX }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: t.addTemplateImage }));
  const added = card(2);
  expect(within(added).getByText(`${t.imageDefaultName} 2`)).not.toBeNull();
  expect(
    within(added).queryByRole("spinbutton", { name: t.imagePositionX }),
  ).not.toBeNull();
  expect(
    within(original).queryByRole("spinbutton", { name: t.imagePositionX }),
  ).toBeNull();
  view.rerender(<Editor active="layout" />);
  expect(
    screen.queryByRole("group", { name: `${t.templateImageControls} 2` }),
  ).toBeNull();
  view.rerender(<Editor />);
  expect(
    within(card(2)).queryByRole("spinbutton", { name: t.imagePositionX }),
  ).not.toBeNull();
  view.rerender(<Editor id="another-template" />);
  expect(
    within(card(2)).queryByRole("spinbutton", { name: t.imagePositionX }),
  ).toBeNull();
  expand(1);
  view.rerender(<Editor />);
  expect(
    within(card(2)).queryByRole("spinbutton", { name: t.imagePositionX }),
  ).not.toBeNull();
  expect(
    within(card(1)).queryByRole("spinbutton", { name: t.imagePositionX }),
  ).toBeNull();
});
it.each(["Enter", "Escape"])(
  "commits or discards an image name through %s",
  async (key) => {
    render(<Editor />);
    action(t.editImageName);
    const input = await screen.findByRole("textbox", { name: t.imageName });
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
  const group = card();
  expect(within(group).queryByRole("spinbutton")).toBeNull();
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
  action(t.editImageName, group);
  const name = await screen.findByRole("textbox", { name: t.imageName });
  fireEvent.change(name, { target: { value: "Chosen by user" } });
  fireEvent.keyDown(name, { key: "Enter" });
  await act(async () => uploaded.resolve("data:image/png;base64,ready"));
  expect(within(group).getByText("Chosen by user")).not.toBeNull();
  expect(within(group).getByRole("img").getAttribute("src")).toBe(
    "data:image/png;base64,ready",
  );
});
it("updates all eight image controls and changes fit with the keyboard", async () => {
  render(
    <Editor
      initial={[{ ...makeImage(1), src: "data:image/png;base64,preview" }]}
    />,
  );
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
  const fit = within(group).getByRole("tablist", { name: t.imageFitLabel });
  const contain = within(fit).getByRole("tab", { name: t.imageFitContain });
  const cover = within(fit).getByRole("tab", { name: t.imageFitCover });
  contain.focus();
  fireEvent.keyDown(contain, { key: "ArrowRight" });
  await waitFor(() => {
    expect(document.activeElement).toBe(cover);
    expect(cover.getAttribute("aria-selected")).toBe("true");
    expect(within(group).getByRole("img").style.objectFit).toBe("cover");
  });
  fireEvent.keyDown(cover, { key: "ArrowLeft" });
  await waitFor(() => {
    expect(document.activeElement).toBe(contain);
    expect(contain.getAttribute("aria-selected")).toBe("true");
    expect(within(group).getByRole("img").style.objectFit).toBe("contain");
  });
});
it("keeps builtin image controls read-only and allows removing an editable image", () => {
  const view = render(<Editor isBuiltIn />);
  const group = expand();
  for (const label of [t.addTemplateImage, t.moreActions, t.uploadImage])
    expect(
      (screen.getByRole("button", { name: label }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  for (const input of group.querySelectorAll<HTMLInputElement>("input"))
    expect(input.disabled).toBe(true);
  const cover = within(group).getByRole("tab", { name: t.imageFitCover });
  expect(cover.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(cover);
  fireEvent.keyDown(cover, { key: "ArrowLeft" });
  expect(cover.getAttribute("aria-selected")).toBe("false");
  expect(
    within(group)
      .getByRole("tab", { name: t.imageFitContain })
      .getAttribute("aria-selected"),
  ).toBe("true");
  expect(prepare).not.toHaveBeenCalled();
  view.rerender(<Editor />);
  action(t.removeImage);
  expect(
    screen.queryByRole("group", { name: `${t.templateImageControls} 1` }),
  ).toBeNull();
});

it("keeps numeric values in sync with keyboard sliders and validates draft colors", () => {
  render(
    <Editor
      initial={[{ ...makeImage(1), src: "data:image/png;base64,preview" }]}
    />,
  );
  const group = expand();
  const opacity = within(group).getByRole<HTMLInputElement>("spinbutton", {
    name: t.imageOpacity,
  });
  fireEvent.keyDown(
    within(group).getByRole("slider", { name: t.imageOpacity }),
    { key: "ArrowLeft" },
  );
  expect(opacity.value).toBe("95");
  const radius = within(group).getByRole<HTMLInputElement>("spinbutton", {
    name: t.imageBorderRadius,
  });
  fireEvent.keyDown(
    within(group).getByRole("slider", { name: t.imageBorderRadius }),
    { key: "ArrowRight" },
  );
  expect(radius.value).toBe("9");

  const color = within(group).getByRole<HTMLInputElement>("textbox", {
    name: t.imageBorderColor,
  });
  const thumbnail = group.querySelector<HTMLElement>(
    '[data-slot="template-image-thumbnail"]',
  )!;
  fireEvent.change(color, { target: { value: "#12" } });
  expect(color.getAttribute("aria-invalid")).toBe("true");
  expect(thumbnail.style.borderColor).toBe("rgb(212, 212, 216)");
  fireEvent.blur(color);
  expect(color.value).toBe("#D4D4D8");
  fireEvent.change(color, { target: { value: "#ABCDEF" } });
  fireEvent.blur(color);
  expect(color.value).toBe("#ABCDEF");
  expect(thumbnail.style.borderColor).toBe("rgb(171, 205, 239)");
});

it("toggles border controls through their label and switch", () => {
  render(<Editor />);
  const group = expand();
  const border = within(group).getByRole("switch", { name: t.imageBorder });
  fireEvent.click(
    within(group).getByText(t.imageBorder, { selector: "label" }),
  );
  expect(border.getAttribute("aria-checked")).toBe("false");
  expect(
    within(group).queryByRole("spinbutton", { name: t.imageBorderWidth }),
  ).toBeNull();
  expect(
    within(group).queryByRole("textbox", { name: t.imageBorderColor }),
  ).toBeNull();
  fireEvent.click(border);
  expect(
    within(group).getByRole<HTMLInputElement>("spinbutton", {
      name: t.imageBorderWidth,
    }).value,
  ).toBe("1");
});

it("clamps geometry to the page without writing an empty numeric draft", () => {
  render(<Editor />);
  const group = expand();
  const x = within(group).getByRole<HTMLInputElement>("spinbutton", {
    name: t.imagePositionX,
  });
  fireEvent.change(x, { target: { value: "999" } });
  fireEvent.blur(x);
  expect(x.value).toBe("180");
  const width = within(group).getByRole<HTMLInputElement>("spinbutton", {
    name: t.imageWidth,
  });
  expect(width.max).toBe("30");
  fireEvent.change(width, { target: { value: "" } });
  expect(width.value).toBe("");
  fireEvent.blur(width);
  expect(width.value).toBe("30");
  fireEvent.change(width, { target: { value: "6.2" } });
  fireEvent.blur(width);
  expect(width.value).toBe("6");
});
