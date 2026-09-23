// @vitest-environment node
import type { ResizeDirection } from "re-resizable";
import { expect, it } from "vitest";

import {
  getTemplateImageResizeLimits,
  moveTemplateImageFrame,
  resizeTemplateImageFrame,
  type TemplateImageGeometry,
} from "@/lib/template-image-geometry";

const frame = Object.freeze({ x: 14, y: 18, width: 30, height: 20 });

it.each([
  [
    { x: 14.24, y: 18.26 },
    { x: 14, y: 18.5 },
  ],
  [
    { x: 14.25, y: 18.75 },
    { x: 14.5, y: 19 },
  ],
  [
    { x: -10, y: -20 },
    { x: 0, y: 0 },
  ],
  [
    { x: 500, y: 500 },
    { x: 180, y: 277 },
  ],
  [
    { x: 179.9, y: 276.9 },
    { x: 180, y: 277 },
  ],
])("snaps and bounds a moved image at %j", (position, expected) => {
  expect(moveTemplateImageFrame(frame, position)).toEqual(expected);
});

it("uses the complete frame dimensions when moving to the page edge", () => {
  expect(
    moveTemplateImageFrame(
      { ...frame, width: 120, height: 120 },
      { x: 210, y: 297 },
    ),
  ).toEqual({ x: 90, y: 177 });
});

it.each([
  ["top", { x: 14, y: 8, width: 30, height: 30 }],
  ["right", { x: 14, y: 18, width: 40, height: 20 }],
  ["bottom", { x: 14, y: 18, width: 30, height: 30 }],
  ["left", { x: 4, y: 18, width: 40, height: 20 }],
  ["topRight", { x: 14, y: 8, width: 40, height: 30 }],
  ["bottomRight", { x: 14, y: 18, width: 40, height: 30 }],
  ["bottomLeft", { x: 4, y: 18, width: 40, height: 30 }],
  ["topLeft", { x: 4, y: 8, width: 40, height: 30 }],
] satisfies [ResizeDirection, TemplateImageGeometry][])(
  "resizes from %s while preserving the opposite anchor",
  (direction, expected) => {
    expect(
      resizeTemplateImageFrame(frame, direction, { width: 40, height: 30 }),
    ).toEqual(expected);
  },
);

it.each([
  ["top", { maxWidth: 120, maxHeight: 38 }],
  ["right", { maxWidth: 120, maxHeight: 120 }],
  ["bottom", { maxWidth: 120, maxHeight: 120 }],
  ["left", { maxWidth: 44, maxHeight: 120 }],
  ["topRight", { maxWidth: 120, maxHeight: 38 }],
  ["bottomRight", { maxWidth: 120, maxHeight: 120 }],
  ["bottomLeft", { maxWidth: 44, maxHeight: 120 }],
  ["topLeft", { maxWidth: 44, maxHeight: 38 }],
] satisfies [ResizeDirection, { maxWidth: number; maxHeight: number }][])(
  "calculates page bounds from the %s anchor",
  (direction, expected) => {
    expect(getTemplateImageResizeLimits(frame, direction)).toEqual(expected);
  },
);

it("keeps the bottom right anchor when shrinking past the minimum size", () => {
  const resized = resizeTemplateImageFrame(frame, "topLeft", {
    width: -10,
    height: 0,
  });
  expect(resized).toEqual({ x: 38, y: 32, width: 6, height: 6 });
  expect(resized.x + resized.width).toBe(frame.x + frame.width);
  expect(resized.y + resized.height).toBe(frame.y + frame.height);
});

it("limits dimensions to 120 mm without moving the opposite anchor", () => {
  const start = Object.freeze({ x: 110, y: 120, width: 50, height: 60 });
  expect(
    resizeTemplateImageFrame(start, "topLeft", { width: 200, height: 200 }),
  ).toEqual({ x: 40, y: 60, width: 120, height: 120 });
  expect(
    resizeTemplateImageFrame({ ...start, x: 0, y: 0 }, "bottomRight", {
      width: 200,
      height: 200,
    }),
  ).toEqual({ x: 0, y: 0, width: 120, height: 120 });
});

it("stops all corner resize directions at their page boundaries", () => {
  const start = Object.freeze({ x: 190, y: 277, width: 20, height: 20 });
  expect(getTemplateImageResizeLimits(start, "bottomRight")).toEqual({
    maxWidth: 20,
    maxHeight: 20,
  });
  expect(
    resizeTemplateImageFrame(start, "bottomRight", { width: 50, height: 50 }),
  ).toEqual(start);
  expect(
    resizeTemplateImageFrame(frame, "topLeft", { width: 100, height: 100 }),
  ).toEqual({ x: 0, y: 0, width: 44, height: 38 });
  expect(
    resizeTemplateImageFrame({ ...frame, x: 190, width: 20 }, "topRight", {
      width: 100,
      height: 100,
    }),
  ).toEqual({ x: 190, y: 0, width: 20, height: 38 });
  expect(
    resizeTemplateImageFrame({ ...frame, y: 277 }, "bottomLeft", {
      width: 100,
      height: 100,
    }),
  ).toEqual({ x: 0, y: 277, width: 44, height: 20 });
});

it("snaps resized dimensions to half millimeters from a fixed gesture snapshot", () => {
  const start = Object.freeze({ x: 14.5, y: 18.5, width: 30, height: 20 });
  expect(
    resizeTemplateImageFrame(start, "topLeft", { width: 25.25, height: 15.74 }),
  ).toEqual({ x: 19, y: 23, width: 25.5, height: 15.5 });
  expect(
    resizeTemplateImageFrame(start, "topLeft", { width: 30.24, height: 20.26 }),
  ).toEqual({ x: 14.5, y: 18, width: 30, height: 20.5 });
  expect(start).toEqual({ x: 14.5, y: 18.5, width: 30, height: 20 });
});

it.each(["left", "right"] satisfies ResizeDirection[])(
  "preserves non-grid vertical geometry when resizing %s",
  (direction) => {
    const start = Object.freeze({ x: 14.5, y: 18.3, width: 30, height: 20.2 });
    const resized = resizeTemplateImageFrame(start, direction, {
      width: 40.24,
      height: 90,
    });
    expect(resized.width).toBe(40);
    expect(resized.y).toBe(start.y);
    expect(resized.height).toBe(start.height);
  },
);

it.each(["top", "bottom"] satisfies ResizeDirection[])(
  "preserves non-grid horizontal geometry when resizing %s",
  (direction) => {
    const start = Object.freeze({ x: 14.3, y: 18.5, width: 30.2, height: 20 });
    const resized = resizeTemplateImageFrame(start, direction, {
      width: 90,
      height: 30.24,
    });
    expect(resized.height).toBe(30);
    expect(resized.x).toBe(start.x);
    expect(resized.width).toBe(start.width);
  },
);
