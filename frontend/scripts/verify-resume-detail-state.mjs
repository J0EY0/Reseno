import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { evaluateTypeScript } from "./typescript-module.mjs";

const frontendRoot = new URL("../", import.meta.url);
const plain = (value) => JSON.parse(JSON.stringify(value));

async function loadModule(path, imports = {}, globals = {}) {
  const source = await readFile(new URL(path, frontendRoot), "utf8");

  return evaluateTypeScript(source, {
    globals: {
      AbortController,
      DOMException,
      console: { error() {}, warn() {} },
      ...globals,
    },
    imports,
  });
}

function createHookRunner() {
  const cells = [];
  let cursor = 0;
  let dirty = false;
  let renderHook;
  let current;
  let effects = [];
  const sameDependencies = (left, right) =>
    left &&
    right &&
    left.length === right.length &&
    left.every((value, index) => Object.is(value, right[index]));
  function useMemo(factory, dependencies) {
    const index = cursor++;
    if (
      !cells[index] ||
      !sameDependencies(cells[index].dependencies, dependencies)
    ) {
      cells[index] = { dependencies, value: factory() };
    }
    return cells[index].value;
  }
  function effect(callback, dependencies) {
    const index = cursor++;
    const previous = cells[index];
    if (!previous || !sameDependencies(previous.dependencies, dependencies)) {
      effects.push({ callback, index, previous });
      cells[index] = { ...previous, dependencies };
    }
  }
  const react = {
    useCallback: (callback, dependencies) =>
      useMemo(() => callback, dependencies),
    useDeferredValue: (value) => value,
    useEffect: effect,
    useLayoutEffect: effect,
    useMemo,
    useRef(value) {
      const index = cursor++;
      cells[index] ??= { current: value };
      return cells[index];
    },
    useState(initial) {
      const index = cursor++;
      cells[index] ??= {
        value: typeof initial === "function" ? initial() : initial,
      };
      cells[index].set ??= (next) => {
        const value =
          typeof next === "function" ? next(cells[index].value) : next;
        if (!Object.is(cells[index].value, value)) {
          cells[index].value = value;
          dirty = true;
        }
      };
      return [cells[index].value, cells[index].set];
    },
  };
  const runner = {
    react,
    window: { setTimeout: () => 0, clearTimeout() {} },
    mount(hook) {
      renderHook = hook;
      return runner.render();
    },
    render() {
      dirty = true;
      return runner.flush();
    },
    flush() {
      let commits = 0;
      while (dirty) {
        assert.ok(
          ++commits < 30,
          "The hook must settle without a render/effect loop.",
        );
        dirty = false;
        cursor = 0;
        effects = [];
        current = renderHook();
        for (const pending of effects) {
          pending.previous?.cleanup?.();
          cells[pending.index].cleanup = pending.callback();
        }
      }
      return current;
    },
    unmount() {
      for (const cell of cells) cell.cleanup?.();
    },
    get current() {
      return current;
    },
  };
  return runner;
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
}

function resumeItem(id = "resume-a") {
  return {
    id,
    title: "Original title",
    updatedAt: "2026-09-01T00:00:00.000Z",
    documentLocale: "en",
    jobBrief: "Original job brief",
    template: "minimal",
    templateSettings: null,
    typography: { fontFamily: "inter", fontSize: 16 },
    resume: {
      schemaVersion: 2,
      basic: { name: "Ada", headline: "Engineer" },
      sections: [],
    },
  };
}
const detail = (resume, versionId = "version-a") => ({
  resume,
  versionId,
  savedAt: resume.updatedAt,
});
const tracking = await loadModule("src/lib/workspace-change-tracking.ts");
const messages = { loadError: "Request failed" };
const toast = { dismiss() {}, error() {} };

function measuredTracking() {
  const counts = { fingerprints: 0, diffs: 0 };
  return {
    counts,
    module: {
      ...tracking,
      createResumeFingerprint(...args) {
        counts.fingerprints += 1;
        return tracking.createResumeFingerprint(...args);
      },
      countResumeChanges(...args) {
        counts.diffs += 1;
        return tracking.countResumeChanges(...args);
      },
    },
  };
}

async function sessionFixture(initial = resumeItem()) {
  const runner = createHookRunner();
  const measured = measuredTracking();
  const { useResumeDetailSession } = await loadModule(
    "src/components/workspace/use-resume-detail-session.ts",
    {
      react: runner.react,
      "@/lib/resume": { createEmptyResume: () => resumeItem().resume },
      "@/lib/workspace-change-tracking": measured.module,
    },
  );
  runner.mount(() => useResumeDetailSession({ initialResume: initial }));
  return { runner, counts: measured.counts };
}

{
  const initial = resumeItem();
  const { runner } = await sessionFixture(initial);
  const getSnapshot = runner.current.getSnapshot;
  const template = {
    id: "modern",
    typography: { fontFamily: "noto-sans-sc", fontSize: 18 },
    settings: { pagePaddingX: 24, pagePaddingY: 30 },
  };
  runner.current.applyTemplate(template);
  runner.flush();
  assert.deepEqual(
    plain(runner.current.document),
    {
      ...initial,
      template: template.id,
      typography: template.typography,
      templateSettings: template.settings,
    },
    "Applying a template must replace its id, typography and settings together without changing the document content.",
  );
  runner.current.updateContent((resume) => ({
    ...resume,
    basic: { ...resume.basic, name: "Grace" },
  }));
  runner.current.rename("Edited title");
  runner.current.updateStyle(({ typography }) => ({
    typography: { ...typography, fontSize: 20 },
  }));
  runner.current.updateStyle(({ templateSettings }) => ({
    templateSettings: { ...templateSettings, pagePaddingX: 28 },
  }));
  assert.equal(
    getSnapshot("before-commit").resume.basic.name,
    "Ada",
    "Async snapshots must expose the committed document until the next render commits.",
  );
  runner.flush();
  assert.equal(
    runner.current.getSnapshot,
    getSnapshot,
    "Async save and discard callers must retain a stable snapshot getter.",
  );
  assert.deepEqual(
    plain(getSnapshot("request-time")),
    { ...plain(runner.current.document), updatedAt: "request-time" },
    "Visible content and save snapshots must include the same edited fields.",
  );
  assert.equal(runner.current.resume.basic.name, "Grace");
  assert.equal(runner.current.document.title, "Edited title");
  assert.equal(runner.current.jobBrief, initial.jobBrief);
  assert.equal(runner.current.template, template.id);
  assert.deepEqual(plain(runner.current.typography), {
    fontFamily: "noto-sans-sc",
    fontSize: 20,
  });
  assert.deepEqual(
    plain(runner.current.templateSettings),
    { pagePaddingX: 28, pagePaddingY: 30 },
    "Queued partial style operations must preserve both the template defaults and earlier edits.",
  );
  assert.equal(
    runner.current.fingerprint,
    tracking.createResumeFingerprint(runner.current.document),
  );
  runner.unmount();
}

{
  const { runner } = await sessionFixture();
  const getter = runner.current.getSnapshot;
  const submitted = getter("submitted");
  runner.current.toggleSection("basic");
  runner.flush();
  const nextDocument = {
    ...resumeItem("resume-b"),
    title: "Next document",
    jobBrief: "Next job",
  };
  runner.current.hydrate(nextDocument);
  runner.flush();
  assert.equal(
    runner.current.openSectionId,
    null,
    "Hydration must close the previous document's editor section.",
  );
  assert.deepEqual(
    plain(getter("next-time")),
    { ...nextDocument, updatedAt: "next-time" },
    "The stable getter must follow a hydrated document rather than retain the old document.",
  );
  runner.current.adoptSavedResume(
    { ...submitted, title: "Old receipt", updatedAt: "late-save" },
    submitted,
  );
  runner.flush();
  assert.deepEqual(
    plain(runner.current.document),
    nextDocument,
    "A late receipt from the previous document must not change the hydrated document.",
  );
  assert.equal(runner.current.resume, nextDocument.resume);
  assert.equal(runner.current.jobBrief, "Next job");
  runner.unmount();
}

{
  const { runner } = await sessionFixture();
  const submitted = runner.current.getSnapshot("submitted");
  const newerTypography = { fontFamily: "noto-sans-sc", fontSize: 20 };
  runner.current.updateContent({
    ...submitted.resume,
    basic: { name: "New typing", headline: "Engineer" },
  });
  runner.current.rename("New title after submit");
  runner.current.updateStyle({
    typography: newerTypography,
    templateSettings: { pagePaddingX: 28 },
  });
  runner.flush();
  runner.current.adoptSavedResume(
    { ...submitted, title: "Server-normalized title", updatedAt: "saved" },
    submitted,
  );
  runner.flush();
  assert.equal(
    runner.current.document.resume.basic.name,
    "New typing",
    "A save receipt must not replace text entered after submission.",
  );
  assert.equal(
    runner.current.document.title,
    "New title after submit",
    "A save receipt must preserve a newer local title.",
  );
  assert.deepEqual(
    plain(runner.current.document.typography),
    newerTypography,
    "A save receipt must preserve style edits made after submission.",
  );
  assert.deepEqual(plain(runner.current.document.templateSettings), {
    pagePaddingX: 28,
  });
  assert.equal(runner.current.document.jobBrief, submitted.jobBrief);
  assert.equal(runner.current.document.updatedAt, "saved");
  const unchangedTitle = runner.current.getSnapshot("submitted-again");
  runner.current.adoptSavedResume(
    { ...unchangedTitle, title: "Normalized unchanged title" },
    unchangedTitle,
  );
  runner.flush();
  assert.equal(
    runner.current.document.title,
    "Normalized unchanged title",
    "An untouched submitted title may adopt server normalization.",
  );
  runner.unmount();
}

{
  const { runner } = await sessionFixture();
  const education = {
    id: "education",
    kind: "education",
    title: "Education",
    items: [],
  };
  const skills = {
    id: "skills",
    kind: "simple_list",
    title: "Skills",
    items: [],
  };
  const fingerprint = runner.current.fingerprint;
  runner.current.toggleSection("basic");
  runner.flush();
  assert.equal(runner.current.openSectionId, "basic");
  assert.equal(
    runner.current.fingerprint,
    fingerprint,
    "Opening an editor section must not dirty the saved document.",
  );
  runner.current.toggleSection("basic");
  runner.flush();
  assert.equal(runner.current.openSectionId, null);
  runner.current.addSection(education);
  runner.current.addSection(skills);
  runner.flush();
  assert.deepEqual(
    plain(runner.current.resume.sections),
    [education, skills],
    "Queued additions must preserve every section.",
  );
  assert.equal(
    runner.current.openSectionId,
    "skills",
    "Adding a section must open that section and close the previous one.",
  );
  runner.current.removeSection("education");
  runner.flush();
  assert.equal(
    runner.current.openSectionId,
    "skills",
    "Removing another section must preserve the currently open editor.",
  );
  runner.current.removeSection("skills");
  runner.flush();
  assert.equal(
    runner.current.openSectionId,
    null,
    "Removing the open section must clear its editor state.",
  );
  assert.deepEqual(plain(runner.current.resume.sections), []);
  runner.current.toggleSection("basic");
  const applied = {
    ...runner.current.resume,
    basic: { name: "Confirmed Agent edit", headline: "Engineer" },
  };
  runner.current.applyAgentResume(applied);
  runner.flush();
  assert.equal(runner.current.resume, applied);
  assert.equal(
    runner.current.openSectionId,
    null,
    "Applying a confirmed Agent result must close stale editor sections.",
  );
  assert.equal(runner.current.getSnapshot("after-apply").resume, applied);
  assert.equal(runner.current.document.title, "Original title");
  assert.equal(runner.current.jobBrief, "Original job brief");
  runner.unmount();
}

{
  const { runner } = await sessionFixture(null);
  assert.equal(runner.current.document, null);
  assert.equal(runner.current.getSnapshot("empty"), null);
  runner.current.updateContent(resumeItem().resume);
  runner.current.rename("Not loaded");
  runner.current.updateStyle({
    typography: { fontFamily: "inter", fontSize: 20 },
  });
  runner.flush();
  assert.equal(
    runner.current.document,
    null,
    "Editor operations must not fabricate a document before loading completes.",
  );
  runner.current.hydrate(resumeItem());
  runner.flush();
  assert.equal(runner.current.getSnapshot("loaded").id, "resume-a");
  runner.unmount();
}

async function saveFixture({ initial = resumeItem(), api = {} } = {}) {
  const runner = createHookRunner();
  const measured = measuredTracking();
  let liveResume = initial;
  let liveFingerprint = tracking.createResumeFingerprint(initial);
  const getFingerprint = () => liveFingerprint;
  const setLiveResume = (value) => {
    liveResume = value;
    liveFingerprint = tracking.createResumeFingerprint(value);
  };
  const checkpoint = { savedAt: initial.updatedAt, versionId: "version-a" };
  const requests = [];
  const { useResumeDetailSave } = await loadModule(
    "src/components/workspace/use-resume-detail-save.ts",
    {
      react: runner.react,
      "@/hooks/use-auth-session-token": {
        useAuthSessionToken: () => "session-token",
      },
      sonner: { toast },
      "@/lib/workspace-change-tracking": measured.module,
      "@/lib/agent-session-run-client": {
        resolveAgentDraftDecision: () =>
          assert.fail("Unexpected Agent decision."),
      },
      "@/lib/workspace-api": {
        async saveResumeApi(id, payload, mode) {
          requests.push({ id, payload: plain(payload), mode });
          return (
            api.save?.(id, payload, mode) ??
            detail(
              {
                ...liveResume,
                ...payload,
                updatedAt: `saved-${requests.length}`,
              },
              `version-${requests.length + 1}`,
            )
          );
        },
        fetchResumeVersionsApi: async () => ({ versions: [checkpoint] }),
        fetchResumeVersionApi: (...args) => api.version(...args),
      },
    },
    { window: runner.window },
  );
  const getSnapshot = (updatedAt) =>
    liveResume ? { ...liveResume, updatedAt } : null;
  runner.mount(() =>
    useResumeDetailSave({
      getFingerprint,
      getSnapshot,
      initialCheckpoint: checkpoint,
      initialResume: initial,
      isLoading: false,
      liveFingerprint,
      liveResume,
      messages,
      onAdoptSavedResume() {},
      onHydrateResume: setLiveResume,
      resumeId: initial.id,
    }),
  );
  return {
    runner,
    requests,
    counts: measured.counts,
    edit(value) {
      setLiveResume(value);
      runner.render();
    },
    get live() {
      return liveResume;
    },
  };
}

{
  const gate = deferred();
  const { runner, edit, requests } = await saveFixture({
    api: { save: () => gate.promise },
  });
  const submitted = { ...resumeItem(), title: "Submitted title" };
  edit(submitted);
  const saving = runner.current.save();
  edit({ ...submitted, title: "Typed while saving" });
  gate.resolve(detail({ ...submitted, updatedAt: "saved" }, "version-b"));
  const saved = await saving;
  runner.flush();
  assert.equal(requests[0].payload.title, "Submitted title");
  assert.equal(
    saved.resume?.title,
    "Submitted title",
    "Save callers must receive the persisted document that belongs to the returned version, without later typing.",
  );
  assert.equal(
    runner.current.hasUnsavedChanges(),
    true,
    "A successful older save must not clear newer local edits.",
  );
  assert.equal(
    runner.current.changeCount,
    1,
    "The confirmed baseline must expose only the newer title as unsaved.",
  );
  assert.equal(runner.current.activeVersionId, "version-b");
  runner.unmount();
}

{
  const fixture = await saveFixture();
  const { runner } = fixture;
  fixture.edit({ ...resumeItem(), title: "Autosaved title" });
  await runner.current.save("autosave");
  runner.flush();
  assert.equal(runner.current.hasUnsavedChanges(), false);
  assert.equal(runner.current.changeCount, 0);
  assert.equal(runner.current.requiresCheckpointPromotion(), true);
  const checkpointReceipt = await runner.current.save("checkpoint");
  runner.flush();
  assert.deepEqual(
    fixture.requests.map(({ mode }) => mode),
    ["autosave", "checkpoint"],
    "A clean autosave still needs a formal checkpoint before leaving.",
  );
  assert.equal(runner.current.requiresCheckpointPromotion(), false);
  assert.deepEqual(
    plain(await runner.current.save()),
    plain(checkpointReceipt),
    "An unchanged document must reuse the persisted snapshot and its matching version.",
  );
  assert.equal(
    fixture.requests.length,
    2,
    "Exporting an already checkpointed document must not add another save.",
  );
  runner.unmount();
}

{
  const selected = {
    ...resumeItem(),
    title: "Historical title",
    updatedAt: "historical-time",
  };
  const fixture = await saveFixture({
    api: { version: async () => detail(selected, "version-old") },
  });
  const { runner } = fixture;
  const current = {
    ...resumeItem(),
    title: "Loaded current title",
    updatedAt: "current-time",
  };
  fixture.edit(current);
  runner.current.hydratePersistedResume(detail(current, "version-current"), [
    { versionId: "version-current", savedAt: current.updatedAt },
    { versionId: "version-old", savedAt: selected.updatedAt },
  ]);
  runner.flush();
  assert.equal(runner.current.hasUnsavedChanges(), false);
  assert.equal(runner.current.changeCount, 0);
  await runner.current.selectVersion("version-old");
  runner.flush();
  assert.equal(fixture.live.title, "Historical title");
  assert.equal(runner.current.activeVersionId, "version-old");
  assert.equal(runner.current.lastSavedAt, "historical-time");
  assert.equal(runner.current.hasUnsavedChanges(), false);
  assert.equal(
    runner.current.changeCount,
    0,
    "Selecting history must move both synchronous and rendered save baselines.",
  );
  fixture.edit({ ...selected, title: "Autosaved historical edit" });
  await runner.current.save("autosave");
  runner.flush();
  assert.equal(runner.current.requiresCheckpointPromotion(), true);
  fixture.edit({ ...selected, title: "Unsaved historical edit" });
  await runner.current.discard();
  runner.flush();
  assert.equal(fixture.live.title, "Autosaved historical edit");
  assert.deepEqual(
    fixture.requests.map(({ mode }) => mode),
    ["autosave", "checkpoint"],
  );
  assert.equal(runner.current.hasUnsavedChanges(), false);
  assert.equal(runner.current.changeCount, 0);
  assert.equal(runner.current.lastSavedAt, "saved-2");
  assert.equal(runner.current.activeVersionId, "version-3");
  assert.equal(
    runner.current.requiresCheckpointPromotion(),
    false,
    "Discarding after autosave must adopt the restoration checkpoint and clear promotion state.",
  );
  runner.unmount();
}

{
  const gate = deferred();
  const fixture = await saveFixture({ api: { version: () => gate.promise } });
  const { runner } = fixture;
  const switching = runner.current.selectVersion("version-old");
  runner.flush();
  fixture.edit({ ...resumeItem(), title: "Typed during version request" });
  gate.resolve(
    detail({ ...resumeItem(), title: "Historical title" }, "version-old"),
  );
  await switching;
  runner.flush();
  assert.equal(
    fixture.live.title,
    "Typed during version request",
    "A delayed historical response must preserve input entered after the request started.",
  );
  assert.equal(runner.current.hasUnsavedChanges(), true);
  assert.equal(runner.current.activeVersionId, "version-a");
  assert.equal(runner.current.isVersionLoading, false);
  runner.unmount();
}

{
  const gate = deferred();
  let requestSignal;
  const fixture = await saveFixture({
    api: {
      version: (_resumeId, _versionId, options) => {
        requestSignal = options?.signal;
        return gate.promise;
      },
    },
  });
  const { runner } = fixture;
  const switching = runner.current.selectVersion("version-old");
  runner.flush();
  runner.unmount();
  assert.equal(
    requestSignal?.aborted,
    true,
    "Leaving the route must cancel its pending historical read.",
  );
  gate.resolve(
    detail({ ...resumeItem(), title: "Historical title" }, "version-old"),
  );
  await switching;
  assert.equal(
    fixture.live.title,
    "Original title",
    "A historical read must never hydrate an unmounted route, even if transport ignores cancellation.",
  );
}

for (const queued of [false, true]) {
  const runner = createHookRunner();
  const gate = deferred();
  const downloads = [];
  const failures = [];
  const savedResume = { ...resumeItem(), template: "custom-a" };
  let writeCount = 0;
  const persistence = await saveFixture({
    api: { save: () => (++writeCount === 1 ? gate.promise : undefined) },
  });
  persistence.edit(savedResume);
  const templates = ["custom-a", "custom-b"].map((id) => ({
    id,
    name: id,
    preset: "minimal",
    description: "",
    layout: {},
    settings: {},
    typography: savedResume.typography,
  }));
  const { createResumeArtifact } = await loadModule("src/lib/export-api.ts", {
    "@/lib/api-client": {},
    "@/lib/template-presets": { isBuiltinTemplateId: (id) => id === "minimal" },
  });
  const { useResumeDetailExport } = await loadModule(
    "src/components/workspace/use-resume-detail-export.ts",
    {
      react: runner.react,
      sonner: {
        toast: {
          success() {},
          error(message) {
            failures.push(message);
          },
        },
      },
      "@/lib/api-error-notifier": {
        notifyApiError: (_error, message) => failures.push(message),
      },
      "@/lib/export-api": {
        downloadResumeJson(resume, definition) {
          downloads.push(createResumeArtifact(resume, definition));
        },
      },
    },
  );
  const save = () => persistence.runner.current.save();
  runner.mount(() =>
    useResumeDetailExport({
      messages: { exportJsonFailed: "Export failed" },
      save,
      templates,
    }),
  );
  const autosaving = queued
    ? persistence.runner.current.save("autosave")
    : null;
  const exporting = runner.current.exportJson();
  const newerResume = {
    ...savedResume,
    title: "Typed during export",
    template: "custom-b",
  };
  persistence.edit(newerResume);
  runner.render();
  gate.resolve(detail(savedResume));
  await autosaving;
  await exporting;
  const exportedResume = queued ? newerResume : savedResume;
  assert.equal(
    downloads.length,
    1,
    "Changing custom templates during a checkpoint must not break JSON export.",
  );
  assert.equal(
    downloads[0].resumes[0].title,
    exportedResume.title,
    "JSON must export the document returned by its own checkpoint, including saves queued behind autosave.",
  );
  assert.equal(
    downloads[0].templates[0].definition.name,
    exportedResume.template,
  );
  assert.equal(failures.length, 0);
  assert.equal(persistence.runner.current.hasUnsavedChanges(), !queued);
  assert.equal(persistence.live.template, "custom-b");
  persistence.runner.unmount();
  runner.unmount();
}

for (const format of ["Pdf", "Images", "Json"]) {
  for (const failureMode of [null, "save", "import"]) {
    const runner = createHookRunner();
    const gate = deferred();
    const calls = [];
    const errors = [];
    let moduleLoads = 0;
    let failImport = failureMode === "import";
    let saveCalls = 0;
    const savedVersion = detail(resumeItem());
    const artifact = { downloadUrl: "/export", fileName: "resume" };
    const imports = {
      react: runner.react,
      sonner: { toast: { success: () => calls.push("success") } },
      "@/lib/api-error-notifier": {
        notifyApiError: (error) => errors.push(error),
      },
    };
    Object.defineProperty(imports, "@/lib/export-api", {
      get() {
        moduleLoads++;
        if (failImport) throw new Error("Chunk unavailable");
        return {
          requestResumePdfExport: async (input) => {
            calls.push(["request", input]);
            return artifact;
          },
          requestResumeImagesExport: async (input) => {
            calls.push(["request", input]);
            return artifact;
          },
          downloadExportedPdf: async (value) => {
            assert.equal(value, artifact);
            calls.push("download");
          },
          downloadExportedFile: async (value) => {
            assert.equal(value, artifact);
            calls.push("download");
          },
          downloadResumeJson: (value) => {
            assert.equal(value, savedVersion.resume);
            calls.push("download");
          },
        };
      },
    });
    const { useResumeDetailExport } = await loadModule(
      "src/components/workspace/use-resume-detail-export.ts",
      imports,
    );
    runner.mount(() =>
      useResumeDetailExport({
        messages: {},
        templates: [{ id: "minimal" }],
        save: () => {
          saveCalls++;
          return gate.promise;
        },
      }),
    );
    assert.equal(
      moduleLoads,
      0,
      "Mounting the editor must not load its export module.",
    );
    const exporting = runner.current[`export${format}`]();
    runner.flush();
    assert.equal(runner.current.isExporting, true);
    await runner.current[`export${format}`]();
    assert.equal(
      saveCalls,
      1,
      "A repeated click must not start another checkpoint.",
    );
    assert.equal(
      moduleLoads,
      1,
      "The export module must load while its checkpoint is pending.",
    );
    assert.deepEqual(
      calls,
      [],
      "No artifact can be requested or downloaded before its checkpoint completes.",
    );
    if (failureMode === "save") gate.reject(new Error("Checkpoint failed"));
    else gate.resolve(savedVersion);
    await exporting;
    runner.flush();
    assert.equal(runner.current.isExporting, false);
    assert.equal(errors.length, failureMode ? 1 : 0);
    if (failureMode) {
      assert.deepEqual(
        calls,
        [],
        "A failed checkpoint or chunk load must never export.",
      );
      failImport = false;
      await runner.current[`export${format}`]();
      runner.flush();
      assert.equal(
        saveCalls,
        2,
        "A failed attempt must release the export guard.",
      );
      assert.equal(runner.current.isExporting, false);
      if (failureMode === "save") assert.deepEqual(calls, []);
      else assert.equal(calls.at(-1), "success");
    } else {
      assert.equal(calls.at(-1), "success");
      assert.equal(calls.at(-2), "download");
      if (format !== "Json")
        assert.deepEqual(plain(calls[0]), [
          "request",
          {
            fileNameSeed: savedVersion.resume.title,
            resumeId: savedVersion.resume.id,
            savedAt: savedVersion.savedAt,
            versionId: savedVersion.versionId,
          },
        ]);
    }
    runner.unmount();
  }
}

{
  const { runner, counts } = await sessionFixture();
  const before = counts.fingerprints;
  for (let index = 0; index < 20; index += 1) {
    runner.current.toggleSection("basic");
    runner.flush();
  }
  assert.equal(
    counts.fingerprints,
    before,
    "Opening sections must reuse the unchanged document fingerprint.",
  );
  const getFingerprint = runner.current.getFingerprint;
  const committedFingerprint = getFingerprint();
  runner.current.rename("Pending title");
  assert.equal(
    getFingerprint(),
    committedFingerprint,
    "Fingerprint and snapshot readers must expose the same committed document.",
  );
  runner.flush();
  assert.equal(runner.current.getFingerprint, getFingerprint);
  assert.notEqual(getFingerprint(), committedFingerprint);
  assert.equal(
    getFingerprint(),
    tracking.createResumeFingerprint(runner.current.getSnapshot("now")),
  );
  assert.equal(
    counts.fingerprints,
    before + 1,
    "A document edit must compute its fingerprint once.",
  );
  runner.unmount();
}

{
  const { runner, counts, edit } = await saveFixture();
  edit({ ...resumeItem(), title: "Edited title" });
  const before = { ...counts };
  for (let index = 0; index < 20; index += 1) {
    runner.render();
    assert.equal(runner.current.hasUnsavedChanges(), true);
    assert.equal(runner.current.changeCount, 1);
  }
  assert.deepEqual(
    counts,
    before,
    "Unrelated renders and repeated leave checks must reuse document fingerprints and change counts.",
  );
  await runner.current.save();
  assert.equal(
    runner.current.hasUnsavedChanges(),
    false,
    "A completed save must advance the synchronous baseline before React commits.",
  );
  runner.flush();
  assert.equal(runner.current.changeCount, 0);
  assert.equal(runner.current.activeVersionId, "version-2");
  assert.equal(runner.current.lastSavedAt, "saved-1");
  runner.unmount();
}

console.log("Resume detail snapshots and save baselines verified.");

{
  const runner = createHookRunner();
  const counts = { fingerprints: 0, changes: 0 };
  let template = {
    id: "template-performance",
    name: "Original template",
    updatedAt: "2026-09-01T00:00:00.000Z",
    isBuiltIn: false,
    layout: {
      images: [
        {
          id: "image-a",
          src: "data:image/png;base64," + "a".repeat(200_000),
          x: 10,
          y: 10,
        },
      ],
    },
  };
  const { useTemplateDetailSave } = await loadModule(
    "src/components/workspace/use-template-detail-save.ts",
    {
      react: runner.react,
      sonner: { toast },
      "@/hooks/use-auth-session-token": {
        useAuthSessionToken: () => "session-token",
      },
      "@/lib/api-error-notifier": { notifyApiError() {} },
      "@/lib/workspace-api": {
        discardTemplateChangesApi() {
          throw new Error("Unexpected discard request.");
        },
        async saveTemplateApi(_id, snapshot) {
          return {
            template: { ...snapshot, updatedAt: "2026-09-01T00:00:01.000Z" },
            checkpoint: null,
          };
        },
      },
      "@/lib/workspace-change-tracking": {
        ...tracking,
        createTemplateFingerprint(...args) {
          counts.fingerprints += 1;
          return tracking.createTemplateFingerprint(...args);
        },
        countTemplateChanges(...args) {
          counts.changes += 1;
          return tracking.countTemplateChanges(...args);
        },
      },
    },
    {
      window: {
        ...runner.window,
        addEventListener() {},
        removeEventListener() {},
      },
    },
  );
  runner.mount(() =>
    useTemplateDetailSave({
      initialCheckpoint: null,
      isLoading: false,
      messages,
      template,
      onAdoptSavedTemplate(saved, accepted) {
        if (accepted.has(tracking.createTemplateFingerprint(template)))
          template = saved;
      },
      onRestoreTemplate(saved) {
        template = saved;
      },
    }),
  );
  const initialCounts = { ...counts };
  for (let index = 0; index < 20; index += 1) {
    runner.render();
    assert.equal(runner.current.hasUnsavedChanges(), false);
  }
  assert.deepEqual(
    counts,
    initialCounts,
    "Unchanged renders and leave checks must reuse template fingerprints and diffs.",
  );
  template = {
    ...template,
    layout: {
      ...template.layout,
      images: [{ ...template.layout.images[0], x: 15 }],
    },
  };
  runner.render();
  assert.equal(counts.fingerprints - initialCounts.fingerprints, 1);
  assert.equal(counts.changes - initialCounts.changes, 1);
  assert.equal(runner.current.hasUnsavedChanges(), true);
  assert.equal(runner.current.changeCount, 1);
  await runner.current.save();
  assert.equal(
    runner.current.hasUnsavedChanges(),
    false,
    "Saving must establish its baseline before the next React commit.",
  );
  runner.render();
  assert.equal(runner.current.changeCount, 0);
  runner.unmount();
}
