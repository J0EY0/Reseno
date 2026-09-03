export const A4_WIDTH_PX = (210 / 25.4) * 96;
export const DOCUMENT_CANVAS_DEFAULT_SCALE = 0.9;
export const DOCUMENT_CANVAS_MIN_SCALE = 0.25;
export const DOCUMENT_CANVAS_MAX_SCALE = 2;

const DOCUMENT_CANVAS_HORIZONTAL_GUTTER_PX = 48;

export function clampDocumentCanvasScale(scale: number) {
  return Math.min(
    DOCUMENT_CANVAS_MAX_SCALE,
    Math.max(DOCUMENT_CANVAS_MIN_SCALE, scale),
  );
}

export function resolveDocumentCanvasScalePreference(value: string | null) {
  if (!value) {
    return DOCUMENT_CANVAS_DEFAULT_SCALE;
  }

  const scale = Number(value);
  return Number.isFinite(scale)
    ? clampDocumentCanvasScale(scale)
    : DOCUMENT_CANVAS_DEFAULT_SCALE;
}

export function getFitWidthScale(viewportWidth: number) {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) {
    return null;
  }

  return clampDocumentCanvasScale(
    (viewportWidth - DOCUMENT_CANVAS_HORIZONTAL_GUTTER_PX) / A4_WIDTH_PX,
  );
}
