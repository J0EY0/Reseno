import assert from "node:assert/strict";
import { it } from "vitest";
import {
  A4_WIDTH_PX,
  DOCUMENT_CANVAS_DEFAULT_SCALE,
  DOCUMENT_CANVAS_MAX_SCALE,
  DOCUMENT_CANVAS_MIN_SCALE,
  clampDocumentCanvasScale,
  getFitWidthScale,
  resolveDocumentCanvasScalePreference,
} from "@/components/preview/document-canvas-model";

it("clamps saved and fitted canvas zoom across invalid inputs and viewport sizes", () => {
  assert.equal(
    clampDocumentCanvasScale(0),
    DOCUMENT_CANVAS_MIN_SCALE,
    "Canvas zoom must stop at its minimum.",
  );
  assert.equal(
    clampDocumentCanvasScale(3),
    DOCUMENT_CANVAS_MAX_SCALE,
    "Canvas zoom must stop at its maximum.",
  );
  assert.equal(DOCUMENT_CANVAS_DEFAULT_SCALE, 0.9);
  assert.equal(
    resolveDocumentCanvasScalePreference(null),
    DOCUMENT_CANVAS_DEFAULT_SCALE,
  );
  assert.equal(
    resolveDocumentCanvasScalePreference("not-a-number"),
    DOCUMENT_CANVAS_DEFAULT_SCALE,
  );
  assert.equal(resolveDocumentCanvasScalePreference("1.2"), 1.2);
  assert.equal(
    resolveDocumentCanvasScalePreference("4"),
    DOCUMENT_CANVAS_MAX_SCALE,
  );
  assert.equal(getFitWidthScale(0), null);
  assert.equal(getFitWidthScale(Number.NaN), null);
  assert.equal(getFitWidthScale(24), DOCUMENT_CANVAS_MIN_SCALE);
  assert.equal(getFitWidthScale(A4_WIDTH_PX + 48), 1);
  assert((getFitWidthScale(A4_WIDTH_PX * 2) ?? 0) > 1);
  assert.equal(
    getFitWidthScale(A4_WIDTH_PX * 3 + 48),
    DOCUMENT_CANVAS_MAX_SCALE,
  );
});
