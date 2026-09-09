import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { evaluateTypeScript } from "./typescript-module.mjs";

const root = new URL("../", import.meta.url);
const [source, presetsSource] = await Promise.all([
  readFile(new URL("src/lib/templates.ts", root), "utf8"),
  readFile(
    new URL("../backend/app/services/template_presets.json", root),
    "utf8",
  ),
]);
const presets = JSON.parse(presetsSource);
let nextId = 0;
const templates = evaluateTypeScript(source, {
  imports: {
    "@/lib/template-presets": {
      builtinTemplateIds: Object.keys(presets),
      getBuiltinTemplatePreset: (id) => presets[id],
    },
    "@/lib/resume": { createId: (prefix) => `${prefix}-${++nextId}` },
  },
});
const plain = (value) => JSON.parse(JSON.stringify(value));

test("partial template images use their domain defaults without becoming tiny or transparent", () => {
  const image = templates.createTemplateLayout("minimal", {
    images: [
      { id: "image-a", name: "Logo", src: "data:image/png;base64,AA==" },
    ],
  }).images[0];
  assert.deepEqual(plain(image), {
    ...plain(templates.DEFAULT_TEMPLATE_IMAGE),
    id: "image-a",
    name: "Logo",
    src: "data:image/png;base64,AA==",
  });
});

test("image creation and repeated layout normalization preserve the same appearance", () => {
  const image = templates.createTemplateImageElement(3, "Image");
  let layout = { images: [image] };
  for (let index = 0; index < 5; index++) {
    layout = templates.createTemplateLayout("minimal", layout);
    assert.deepEqual(plain(layout.images[0]), plain(image));
  }
  assert.equal(image.name, "Image 3");
  assert.equal(
    templates.createTemplateImageElement(1, "Image", {
      avatarPosition: "right",
    }).x,
    14,
  );
  assert.equal(
    templates.createTemplateImageElement(1, "Image", { avatarPosition: "left" })
      .x,
    166,
  );
});

test("explicit image values remain authoritative while missing values use defaults", () => {
  const image = templates.createTemplateLayout("minimal", {
    images: [
      {
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
      },
    ],
  }).images[0];
  assert.equal(image.x, 0);
  assert.equal(image.y, 0);
  assert.equal(image.width, 30);
  assert.equal(image.height, 20);
  assert.equal(image.borderWidth, 0);
  assert.equal(image.borderRadius, 0);
  assert.equal(image.opacity, 0.5);
  assert.equal(image.visible, false);
  assert.equal(image.objectFit, "cover");
});

const imageUploadSource = await readFile(
  new URL("src/lib/template-image-upload.ts", root),
  "utf8",
);
const imageUpload = evaluateTypeScript(imageUploadSource, {
  imports: {
    "@/lib/avatar": {
      readAvatarFileAsDataUrl() {
        assert.fail(
          "Oversized animated originals must be rejected before reading or rasterizing.",
        );
      },
    },
  },
});

for (const format of ["png", "webp"]) {
  test(`oversized animated ${format} must not silently become a static frame`, async () => {
    const bytes = new Uint8Array(1024 * 1024 + 1);
    const view = new DataView(bytes.buffer);
    const text = (offset, value) =>
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
    await assert.rejects(
      imageUpload.prepareTemplateImage(
        new File([bytes], `animation.${format}`, { type: `image/${format}` }),
      ),
      { message: "templateImageOriginalTooLarge" },
    );
  });
}
