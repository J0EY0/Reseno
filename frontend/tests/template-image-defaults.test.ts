// @vitest-environment node
import { expect, it, vi } from "vitest";

import { readAvatarFileAsDataUrl } from "@/lib/avatar";
import { prepareTemplateImage } from "@/lib/template-image-upload";
import {
  createTemplateImageElement,
  createTemplateLayout,
  DEFAULT_TEMPLATE_IMAGE,
} from "@/lib/templates";
import type { ResumeTemplateImageElement } from "@/types/resume";

vi.mock("@/lib/avatar", () => ({ readAvatarFileAsDataUrl: vi.fn() }));

function normalizeImage(image: unknown) {
  return createTemplateLayout("minimal", {
    images: [image as ResumeTemplateImageElement],
  }).images[0];
}

it("fills partial image defaults without making the image tiny or transparent", () => {
  const image = {
    id: "image-a",
    name: "Logo",
    src: "data:image/png;base64,AA==",
  };
  expect(normalizeImage(image)).toEqual({
    ...DEFAULT_TEMPLATE_IMAGE,
    ...image,
  });
});

it("preserves image appearance over repeated normalization and positions it opposite the avatar", () => {
  const image = createTemplateImageElement(3, "Image");
  let normalized = image;
  for (let index = 0; index < 5; index++) {
    normalized = normalizeImage(normalized);
    expect(normalized).toEqual(image);
  }
  expect(image.name).toBe("Image 3");
  for (const [avatarPosition, x] of [
    ["right", 14],
    ["left", 166],
  ] as const) {
    expect(createTemplateImageElement(1, "Image", { avatarPosition }).x).toBe(
      x,
    );
  }
});

it("preserves explicit zero, hidden and fit values while defaulting missing dimensions", () => {
  expect(
    normalizeImage({
      id: "image-b",
      x: 0,
      y: 0,
      width: null,
      height: undefined,
      borderWidth: 0,
      borderRadius: 0,
      opacity: 0.5,
      visible: false,
      objectFit: "cover",
    }),
  ).toMatchObject({
    x: 0,
    y: 0,
    width: 30,
    height: 20,
    borderWidth: 0,
    borderRadius: 0,
    opacity: 0.5,
    visible: false,
    objectFit: "cover",
  });
});

it.each(["png", "webp"])(
  "rejects oversized animated %s before reading or rasterizing it",
  async (format) => {
    const bytes = new Uint8Array(1024 * 1024 + 1);
    const view = new DataView(bytes.buffer);
    const text = (offset: number, value: string) =>
      bytes.set(new TextEncoder().encode(value), offset);
    if (format === "png") {
      bytes.set([137, 80, 78, 71, 13, 10, 26, 10]);
      view.setUint32(8, 13);
      text(12, "IHDR");
      view.setUint32(16, 100);
      view.setUint32(20, 100);
      view.setUint32(33, 8);
      text(37, "acTL");
      view.setUint32(41, 2);
    } else {
      text(0, "RIFF");
      view.setUint32(4, bytes.length - 8, true);
      text(8, "WEBPVP8X");
      view.setUint32(16, 10, true);
      view.setUint8(20, 2);
    }
    await expect(
      prepareTemplateImage(
        new File([bytes], `animation.${format}`, { type: `image/${format}` }),
      ),
    ).rejects.toThrow("templateImageOriginalTooLarge");
    expect(readAvatarFileAsDataUrl).not.toHaveBeenCalled();
  },
);
