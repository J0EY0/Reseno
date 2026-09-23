import type { ResizeDirection } from "re-resizable";

import type { ResumeTemplateImageElement } from "@/types/resume";

export type TemplateImageGeometry = Pick<
  ResumeTemplateImageElement,
  "x" | "y" | "width" | "height"
>;

function snapWithinBounds(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.round(value * 2) / 2));
}

export function moveTemplateImageFrame(
  frame: TemplateImageGeometry,
  position: { x: number; y: number },
) {
  return {
    x: snapWithinBounds(position.x, 0, Math.max(0, 210 - frame.width)),
    y: snapWithinBounds(position.y, 0, Math.max(0, 297 - frame.height)),
  };
}

export function getTemplateImageResizeLimits(
  frame: TemplateImageGeometry,
  direction: ResizeDirection,
) {
  const edge = direction.toLowerCase();
  return {
    maxWidth: Math.max(
      6,
      Math.min(
        120,
        edge.includes("left") ? frame.x + frame.width : 210 - frame.x,
      ),
    ),
    maxHeight: Math.max(
      6,
      Math.min(
        120,
        edge.includes("top") ? frame.y + frame.height : 297 - frame.y,
      ),
    ),
  };
}

export function resizeTemplateImageFrame(
  frame: TemplateImageGeometry,
  direction: ResizeDirection,
  size: { width: number; height: number },
): TemplateImageGeometry {
  const edge = direction.toLowerCase();
  const { maxWidth, maxHeight } = getTemplateImageResizeLimits(
    frame,
    direction,
  );
  const width =
    edge.includes("left") || edge.includes("right")
      ? snapWithinBounds(size.width, 6, maxWidth)
      : frame.width;
  const height =
    edge.includes("top") || edge.includes("bottom")
      ? snapWithinBounds(size.height, 6, maxHeight)
      : frame.height;

  return {
    x: edge.includes("left") ? frame.x + frame.width - width : frame.x,
    y: edge.includes("top") ? frame.y + frame.height - height : frame.y,
    width,
    height,
  };
}
