import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createAspectAvatarCrop } from "@/components/editor/avatar-crop-geometry";
import { AvatarCropDialog } from "@/components/editor/avatar-crop-dialog";
import { defaultMessages as t } from "@/i18n";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restore: () => void;
beforeEach(() => {
  restore = installPanelBrowserApis();
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});
it.each([
  [
    { x: 180, y: 200 },
    { x: 100, y: 100, width: 80, height: 100 },
  ],
  [
    { x: 20, y: 0 },
    { x: 20, y: 0, width: 80, height: 100 },
  ],
])(
  "preserves the 4:5 crop in either drawing direction: %j",
  (end, expected) => {
    expect(
      createAspectAvatarCrop({ x: 100, y: 100 }, end, {
        width: 520,
        height: 420,
      }),
    ).toEqual(expected);
  },
);
it("captures the drawing pointer and exports natural-image crop coordinates through the real controller and canvas", async () => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const images: HTMLImageElement[] = [];
  vi.stubGlobal("Image", function () {
    const image = document.createElement("img");
    Object.defineProperties(image, {
      naturalWidth: { value: 1040 },
      naturalHeight: { value: 840 },
    });
    images.push(image);
    return image;
  });
  const drawImage = vi.fn();
  const fillRect = vi.fn();
  const context = { fillStyle: "", drawImage, fillRect };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    context as unknown as CanvasRenderingContext2D,
  );
  const serialize = vi
    .spyOn(HTMLCanvasElement.prototype, "toDataURL")
    .mockReturnValue("data:image/jpeg;base64,Y3JvcHBlZA==");
  render(
    <AvatarCropDialog
      t={t}
      source="data:image/png;base64,c291cmNl"
      open
      onConfirm={onConfirm}
      onCancel={onCancel}
    />,
  );
  const image = screen.getByRole("img", { name: t.cropAvatar });
  Object.defineProperties(image, {
    naturalWidth: { value: 1040 },
    naturalHeight: { value: 840 },
  });
  fireEvent.load(image);
  const stage = image.parentElement!;
  expect(stage.style.width).toBe("520px");
  expect(stage.style.height).toBe("420px");
  vi.spyOn(stage, "getBoundingClientRect").mockReturnValue(
    new DOMRect(10, 20, 520, 420),
  );
  const capture = vi.fn(),
    release = vi.fn();
  Object.assign(stage, {
    setPointerCapture: capture,
    hasPointerCapture: () => true,
    releasePointerCapture: release,
  });
  function pointer(type: string, x: number, y: number, id = 7) {
    const event = new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      clientX: x + 10,
      clientY: y + 20,
    });
    Object.defineProperty(event, "pointerId", { value: id });
    fireEvent(stage, event);
  }
  expect(
    (screen.getByRole("button", { name: t.applyCrop }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  pointer("pointerdown", 100.25, 100.25);
  expect(capture).toHaveBeenCalledExactlyOnceWith(7);
  pointer("pointermove", 400, 400, 9);
  expect(
    (screen.getByRole("button", { name: t.applyCrop }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  pointer("pointermove", 220.5, 250.5625);
  pointer("pointerup", 220.5, 250.5625);
  expect(release).toHaveBeenCalledExactlyOnceWith(7);
  const preview = Array.from(
    document.querySelectorAll<HTMLElement>("[style]"),
  ).find((element) =>
    element.style.backgroundImage.includes("data:image/png"),
  )!;
  expect(parseFloat(preview.style.backgroundPosition)).toBeCloseTo(
    (-100.25 * 108) / 120.25,
  );
  expect(parseFloat(preview.style.backgroundSize)).toBeCloseTo(
    (520 * 108) / 120.25,
  );
  fireEvent.click(screen.getByRole("button", { name: t.applyCrop }));
  expect(images).toHaveLength(1);
  expect(onConfirm).not.toHaveBeenCalled();
  expect(
    (screen.getByRole("button", { name: t.cancel }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(onCancel).not.toHaveBeenCalled();
  await act(async () => {
    images[0].dispatchEvent(new Event("load"));
  });
  await waitFor(() =>
    expect(onConfirm).toHaveBeenCalledExactlyOnceWith(
      "data:image/jpeg;base64,Y3JvcHBlZA==",
    ),
  );
  expect(drawImage).toHaveBeenCalledExactlyOnceWith(
    images[0],
    201,
    201,
    241,
    301,
    0,
    0,
    800,
    1000,
  );
  expect(fillRect).toHaveBeenCalledExactlyOnceWith(0, 0, 800, 1000);
  expect(context.fillStyle).toBe("#ffffff");
  expect(serialize).toHaveBeenCalledExactlyOnceWith("image/jpeg", 0.92);
  expect(
    (screen.getByRole("button", { name: t.applyCrop }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
  pointer("pointerdown", 20, 20);
  pointer("pointercancel", 20, 20);
  expect(release).toHaveBeenCalledTimes(2);
  expect(
    (screen.getByRole("button", { name: t.applyCrop }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
