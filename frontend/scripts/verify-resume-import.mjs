import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScriptModule } from "./typescript-module.mjs";

const moduleUrl = new URL(
  "../src/components/workspace/resume-gallery-import.ts",
  import.meta.url,
);
const file = { name: "backup.json", type: "application/json" };
const item = (title, template = "minimal") => ({
  title,
  template,
  documentLocale: "en",
  resume: {},
  jobBrief: "",
  typography: {},
  templateSettings: null,
});

async function harness(bundle, { failResume, failTemplate } = {}) {
  const resumeCalls = [];
  const templateCalls = [];
  const imported = await loadTypeScriptModule(moduleUrl, {
    globals: { AbortController },
    imports: {
      "@/lib/import-api": { importResumePayload: async () => bundle },
      "@/lib/resume-title": { normalizeResumeTitle: (value) => value },
      "@/lib/workspace-api": {
        createTemplateApi: async (definition) => {
          templateCalls.push(definition.name);
          if (failTemplate?.(definition, templateCalls))
            throw new Error("Template rejected");
          return {
            template: { ...definition, id: `template-${definition.name}` },
          };
        },
        createResumeApi: async (request) => {
          resumeCalls.push({ ...request });
          if (failResume?.(request, resumeCalls))
            throw new Error("Resume rejected");
          return {
            resume: { ...request, id: `resume-${request.title}` },
            savedAt: "now",
            versionId: "1",
          };
        },
      },
    },
  });
  return { ...imported, resumeCalls, templateCalls };
}

test("partial resume imports publish successes and retry only unfinished documents", async () => {
  const api = await harness(
    {
      templates: [
        { ref: "custom:0", definition: { name: "A" } },
        { ref: "custom:1", definition: { name: "B" } },
      ],
      resumes: [
        item("1", "custom:0"),
        item("2", "custom:1"),
        item("3"),
        item("4"),
        item("5"),
      ],
    },
    {
      failResume: (request, calls) =>
        request.title === "4" &&
        calls.filter((entry) => entry.title === "4").length === 1,
    },
  );
  const published = [];
  const first = await api.importResumesIntoWorkspace(file, {
    onResumeSaved: (saved) => published.push(saved.resume.title),
  });
  assert.deepEqual(published, ["1", "2", "3", "5"]);
  assert.equal(first.importedCount, 4);
  assert.equal(first.remainingCount, 1);
  const second = await first.retry({
    onResumeSaved: (saved) => published.push(saved.resume.title),
  });
  assert.equal(second.importedCount, 5);
  assert.equal(second.remainingCount, 0);
  assert.equal(second.retry, null);
  assert.deepEqual(api.templateCalls, ["A", "B"]);
  assert.deepEqual(
    api.resumeCalls.map((entry) => entry.title),
    ["1", "2", "3", "4", "5", "4"],
  );
});

test("a failed embedded template delays only its dependents and is reused after retry", async () => {
  const api = await harness(
    {
      templates: [
        { ref: "custom:0", definition: { name: "A" } },
        { ref: "custom:1", definition: { name: "B" } },
      ],
      resumes: [item("A", "custom:0"), item("B", "custom:1"), item("plain")],
    },
    {
      failTemplate: (definition, calls) =>
        definition.name === "A" &&
        calls.filter((name) => name === "A").length === 1,
    },
  );
  const first = await api.importResumesIntoWorkspace(file);
  assert.equal(first.remainingCount, 1);
  assert.deepEqual(
    api.resumeCalls.map((entry) => entry.title),
    ["B", "plain"],
  );
  const second = await first.retry({});
  assert.equal(second.remainingCount, 0);
  assert.deepEqual(api.templateCalls, ["A", "B", "A"]);
  assert.deepEqual(
    api.resumeCalls.map((entry) => entry.template),
    ["template-B", "minimal", "template-A"],
  );
});

test("cancellation preserves committed items and resumes the remaining batch", async () => {
  const api = await harness({
    templates: [],
    resumes: [item("1"), item("2"), item("3")],
  });
  const controller = new AbortController();
  const first = await api.importResumesIntoWorkspace(file, {
    signal: controller.signal,
    onResumeSaved: () => controller.abort(),
  });
  assert.equal(first.importedCount, 1);
  assert.equal(first.remainingCount, 2);
  assert.equal(api.resumeCalls.length, 1);
  const second = await first.retry({});
  assert.equal(second.importedCount, 3);
  assert.equal(second.remainingCount, 0);
  assert.deepEqual(
    api.resumeCalls.map((entry) => entry.title),
    ["1", "2", "3"],
  );
});
