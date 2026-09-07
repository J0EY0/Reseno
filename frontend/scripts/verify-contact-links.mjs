import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

import { evaluateTypeScript } from "./typescript-module.mjs";
import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const root = new URL("..", import.meta.url).pathname;
const helperPath = join(root, "src", "lib", "contact-links.ts");
const source = await readFile(helperPath, "utf8");
const {
  createContactHref,
  normalizeContactFieldType,
} = evaluateTypeScript(source, {
  globals: { URL, Set },
});

assert.equal(normalizeContactFieldType("url"), "url");
assert.equal(normalizeContactFieldType("javascript"), "text");
assert.equal(createContactHref("text", "https://example.com"), null);
assert.equal(
  createContactHref("email", "name@example.com"),
  "mailto:name@example.com",
);
assert.equal(
  createContactHref("phone", "+86 13800000000"),
  "tel:+86 13800000000",
);
assert.equal(
  createContactHref("url", "github.com/example"),
  "https://github.com/example",
);
assert.equal(
  createContactHref("url", "http://example.com/profile"),
  "http://example.com/profile",
);
assert.equal(createContactHref("url", "javascript:alert(1)"), null);
assert.equal(createContactHref("url", "data:text/html,test"), null);
assert.equal(createContactHref("url", "ftp://example.com/file"), null);
assert.equal(createContactHref("email", "https://example.com"), null);
assert.equal(createContactHref("phone", "mailto:name@example.com"), null);
assert.equal(createContactHref("url", "https://"), null);
assert.equal(createContactHref("url", "https://example.com\nunsafe"), null);

const vite = await createServer({
  cacheDir: createViteTestCacheDir(),
  optimizeDeps: { noDiscovery: true },
  root,
  appType: "custom",
  logLevel: "silent",
  server: { middlewareMode: true },
});

try {
  const { ResumeThumbnail } = await vite.ssrLoadModule(
    "/src/components/preview/resume-thumbnail.tsx",
  );
  const thumbnailMarkup = renderToStaticMarkup(
    React.createElement(
      "a",
      { href: "/resume/example" },
      React.createElement(ResumeThumbnail, {
        t: {},
        resume: {
          basic: {
            name: "Example",
            headline: "",
            phone: "+86 13800000000",
            email: "name@example.com",
            location: "",
            avatar: "",
            summary: "",
            customFields: [],
          },
          sections: [
            {
              id: "project-section",
              kind: "project",
              title: "Projects",
              items: [
                {
                  id: "project-item",
                  name: "Linked project",
                  role: "Lead",
                  techStack: [],
                  period: "2026",
                  url: "https://example.com/project",
                  description: "",
                  highlights: [],
                },
              ],
            },
          ],
        },
        fontFamily: "inter",
        fontSize: 16,
        template: {
          id: "minimal",
          preset: "minimal",
          name: "Minimal",
          description: "",
          updatedAt: "",
          isBuiltIn: true,
          layout: {
            basicInfo: "centered",
            section: "ruled",
            timelineItemLayout: "split",
            listItemLayout: "list",
            avatarPosition: "none",
            avatarShape: "rounded",
            avatarWidth: 25,
            avatarHeight: 32,
            avatarOffsetX: 0,
            avatarOffsetY: 0,
            avatarBorderWidth: 0,
            avatarBorderColor: "#e5e7eb",
            images: [],
          },
          typography: {
            fontFamily: "inter",
            fontSize: 16,
          },
          settings: {
            pagePaddingTop: 13,
            pagePaddingX: 12,
            pagePaddingBottom: 11,
            sectionGap: 1.25,
            itemGap: 0.88,
            bodyLineHeight: 1.7,
            nameScale: 2.15,
            sectionTitleScale: 1.28,
            itemTitleScale: 1.02,
            metaScale: 0.92,
            bodyScale: 0.96,
            pageBackground: "#ffffff",
            surfaceColor: "#f8fafc",
            headingColor: "#111827",
            bodyColor: "#334155",
            mutedColor: "#64748b",
            dividerColor: "#202020",
            dividerThickness: 1,
          },
        },
      }),
    ),
  );
  const thumbnailAnchorCount =
    thumbnailMarkup.match(/<a(?:\s|>)/g)?.length ?? 0;

  assert.equal(
    thumbnailAnchorCount,
    1,
    "A thumbnail nested inside a linked gallery card must not render contact anchors.",
  );
} finally {
  await vite.close();
}

console.log("Contact link verification passed.");
