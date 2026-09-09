import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  A4_WIDTH_PX,
  DOCUMENT_CANVAS_DEFAULT_SCALE,
  DOCUMENT_CANVAS_MAX_SCALE,
  DOCUMENT_CANVAS_MIN_SCALE,
  clampDocumentCanvasScale,
  getFitWidthScale,
  resolveDocumentCanvasScalePreference,
} from "../src/components/preview/document-canvas-model.ts";

const documentCanvasSource = readFileSync(
  new URL("../src/components/preview/document-canvas.tsx", import.meta.url),
  "utf8",
);
const documentCanvasHookSource = readFileSync(
  new URL("../src/components/preview/use-document-canvas.ts", import.meta.url),
  "utf8",
);

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
assert(getFitWidthScale(A4_WIDTH_PX * 2) > 1);
assert.equal(getFitWidthScale(A4_WIDTH_PX * 3 + 48), DOCUMENT_CANVAS_MAX_SCALE);
assert.match(
  documentCanvasSource,
  /data-slot="document-canvas-viewport"[\s\S]*?className="[^"]*cursor-default/,
  "The document viewport must retain the standard cursor.",
);
assert.match(
  documentCanvasSource,
  /data-document-canvas-paper[\s\S]*?className="[^"]*\[&_a\]:cursor-default/,
  "Resume paper links must not replace the standard cursor.",
);
assert.match(
  documentCanvasSource,
  /data-slot="document-canvas-controls"[\s\S]*?className="[^"]*cursor-default/,
  "Canvas status controls must retain the standard cursor.",
);
assert.doesNotMatch(
  documentCanvasSource,
  /cursor-grab(?:bing)?/,
  "The document canvas must not expose grab cursors.",
);
assert.match(
  documentCanvasSource,
  /onKeyDown=\{onKeyDown\}/,
  "Canvas zoom shortcuts must be scoped to the document surface.",
);
assert.match(
  documentCanvasHookSource,
  /addEventListener\("wheel", handleWheel, \{ passive: false \}\)/,
  "Trackpad zoom must use a cancelable native wheel listener.",
);
assert.match(
  documentCanvasHookSource,
  /\(!event\.ctrlKey && !event\.metaKey\)/,
  "Plain two-finger scrolling must not trigger canvas zoom.",
);
assert.match(
  documentCanvasHookSource,
  /event\.preventDefault\(\)/,
  "Canvas zoom gestures must prevent browser page zoom.",
);
assert.match(
  documentCanvasHookSource,
  /reseno-document-canvas-scale-v1/,
  "Canvas zoom must use a versioned local preference key.",
);
assert.match(
  documentCanvasHookSource,
  /useState<DocumentCanvasZoom>\(\(\) => \[[\s\S]*?loadDocumentCanvasScale\(\),[\s\S]*?false/,
  "Canvas zoom must start from the saved manual scale rather than fit-to-width.",
);
assert.match(
  documentCanvasHookSource,
  /saveDocumentCanvasScale\(scale\)/,
  "Every resolved canvas scale must be saved locally.",
);
assert.doesNotMatch(
  documentCanvasHookSource,
  /addEventListener\("wheel"[\s\S]{0,200}setScale\(null\)/,
  "Canvas mount must not replace the saved scale with fit-to-width.",
);
console.log("Document canvas zoom model verified.");
