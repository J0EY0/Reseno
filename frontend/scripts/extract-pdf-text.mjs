import { readFile } from "node:fs/promises";

import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";

const inputPath = process.argv[2];
if (!inputPath) {
  throw new Error("Usage: node scripts/extract-pdf-text.mjs <pdf-path>");
}

const loadingTask = getDocument({
  data: new Uint8Array(await readFile(inputPath)),
});
const document = await loadingTask.promise;
const pages = [];

try {
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const content = await page.getTextContent();
    pages.push(
      content.items
        .map((item) =>
          "str" in item ? item.str + (item.hasEOL ? "\n" : "") : "",
        )
        .join(""),
    );
  }
} finally {
  await loadingTask.destroy();
}

process.stdout.write(JSON.stringify(pages));
