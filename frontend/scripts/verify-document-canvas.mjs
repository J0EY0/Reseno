import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const documentCanvasSource = readFileSync(
  new URL("../src/components/preview/document-canvas.tsx", import.meta.url),
  "utf8",
);
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
console.log("Document canvas cursor contracts verified.");
