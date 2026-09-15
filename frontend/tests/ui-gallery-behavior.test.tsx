import {
  act,
  renderHook,
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ComponentProps, ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useResumeGalleryController } from "@/components/use-resume-gallery-controller";
import { useTemplateGalleryController } from "@/components/templates/use-template-gallery-controller";
import { ResumeGallery } from "@/components/resume-gallery";
import { ResumeGalleryCard } from "@/components/resume-gallery-card";
import { TemplateGallery } from "@/components/templates/template-gallery";
import { TemplateGalleryCard } from "@/components/templates/template-gallery-card";
import { GalleryRouteSkeleton } from "@/components/gallery-skeletons";
import { defaultMessages as t } from "@/i18n";
import { createTemplatePreviewResumes } from "@/lib/template-preview-resume";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restore: () => void;
beforeEach(() => {
  restore = installPanelBrowserApis();
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});
function fixtures() {
  const templates = [
    createResumeDetailTemplate("custom-a"),
    createResumeDetailTemplate("custom-b"),
  ].map((item, index) => ({
    ...item,
    name: `Template ${index}`,
    isBuiltIn: false,
  }));
  const resumes = [0, 1].map((i) =>
    createResumeDetailItem({
      id: `resume-${i}`,
      title: `Resume ${i}`,
      template: "custom-a",
    }),
  );
  const resume: ComponentProps<typeof ResumeGallery> = {
    locale: "en",
    t,
    resumes,
    templates,
    defaultTemplateIds: { en: "custom-a", zh: "custom-a" },
    isImporting: false,
    importProgress: null,
    onRetryImport: vi.fn(),
    onCancelImport: vi.fn(),
    isCreating: false,
    openingResumeId: null,
    onPreloadResumeDetail: vi.fn(),
    onOpenResume: vi.fn(),
    onCreateResume: vi.fn(),
    onImportResume: vi.fn(),
    onDeleteResume: vi.fn(),
    onBulkDeleteResumes: vi.fn(),
  };
  const template: ComponentProps<typeof TemplateGallery> = {
    t,
    previewMessages: t,
    previewResumes: createTemplatePreviewResumes(t),
    templates,
    defaultTemplateId: "custom-a",
    templateLocale: "en",
    isImporting: false,
    isCreating: false,
    openingTemplateId: null,
    settingDefaultTemplateId: null,
    onPreloadTemplateDetail: vi.fn(),
    onOpenTemplate: vi.fn(),
    onSetDefaultTemplate: vi.fn(),
    onTemplateLocaleChange: vi.fn(),
    onCreateCustomTemplate: vi.fn(),
    onImportTemplates: vi.fn(),
    onDeleteTemplates: vi.fn(async (ids: string[]) => ids),
  };
  return { resume, template };
}
function assertFlatEmpty(container: HTMLElement, text: string) {
  const empty = screen.getByText(text).closest('[data-slot="empty"]')!;
  expect(empty).not.toBeNull();
  const section = empty.closest("section")!;
  expect(section.classList.contains("border")).toBe(true);
  expect(
    Array.from(empty.classList).filter(
      (token) =>
        token === "border" ||
        (token.startsWith("border-") && token !== "border-dashed") ||
        token.startsWith("bg-") ||
        token.startsWith("shadow"),
    ),
  ).toEqual([]);
  const grid = container.querySelector('[data-slot="gallery-grid"]')!;
  expect(
    empty.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(grid.querySelector('[data-slot="empty"]')).toBeNull();
}
it.each(["resume", "template"] as const)(
  "keeps %s selection, count transitions and confirmed bulk deletion on actual cards",
  async (kind) => {
    const props = fixtures();
    const view =
      kind === "resume" ? (
        <ResumeGallery {...props.resume} />
      ) : (
        <TemplateGallery {...props.template} />
      );
    const { container } = render(<MemoryRouter>{view}</MemoryRouter>);
    const grid = container.querySelector('[data-slot="gallery-grid"]')!;
    expect(
      grid.classList.contains(
        "grid-cols-[repeat(auto-fill,minmax(208px,228px))]",
      ),
    ).toBe(true);
    expect(grid.classList.contains("justify-center")).toBe(true);
    expect(
      grid.querySelectorAll('[data-export-root="resume-page"]'),
    ).toHaveLength(2);
    const create = screen.getByRole("button", {
      name: kind === "resume" ? t.newResume : t.newTemplate,
    });
    expect(
      create.querySelector('svg.lucide-copy-plus[data-icon="inline-start"]'),
    ).not.toBeNull();
    const bulk = container.querySelector<HTMLElement>(
      "[data-gallery-bulk-action]",
    )!;
    const hidden = () => {
      expect(bulk.getAttribute("data-state")).toBe("closed");
      expect(bulk.getAttribute("aria-hidden")).toBe("true");
      expect(bulk.hasAttribute("inert")).toBe(true);
      expect(bulk.style.gridTemplateColumns).toBe("0fr");
      expect(bulk.style.marginLeft).toBe("-0.5rem");
      expect(bulk.style.opacity).toBe("0");
      expect(bulk.style.transform).toBe("translateX(0.25rem) scale(0.98)");
      expect(within(bulk).queryByRole("button")).toBeNull();
    };
    hidden();
    fireEvent.click(screen.getByRole("button", { name: t.selectItems }));
    const label = kind === "resume" ? "Resume" : "Template";
    const first = screen.getByRole("button", { name: `${label} 0` });
    fireEvent.click(first);
    expect(first.getAttribute("aria-pressed")).toBe("true");
    hidden();
    const count = container.querySelector(
      '[data-slot="badge"][aria-live="polite"]',
    )!;
    const one = count.firstElementChild;
    expect(one?.textContent).toBe("1");
    expect(one?.classList.contains("animate-in")).toBe(true);
    expect(one?.classList.contains("duration-150")).toBe(true);
    fireEvent.keyDown(screen.getByRole("button", { name: `${label} 1` }), {
      key: " ",
    });
    expect(count.firstElementChild?.textContent).toBe("2");
    expect(count.firstElementChild).not.toBe(one);
    expect(bulk.getAttribute("data-state")).toBe("open");
    expect(bulk.getAttribute("aria-hidden")).toBe("false");
    expect(bulk.hasAttribute("inert")).toBe(false);
    expect(bulk.style.gridTemplateColumns).toBe("1fr");
    expect(bulk.style.marginLeft).toBe("0px");
    expect(bulk.style.opacity).toBe("1");
    expect(bulk.style.transform).toBe("translateX(0) scale(1)");
    for (const token of ["transition-all", "duration-150", "ease-out"])
      expect(bulk.classList.contains(token)).toBe(true);
    const remove = within(bulk).getByRole("button", { name: t.bulkDelete });
    expect(
      remove.querySelector('svg.lucide-trash-2[data-icon="inline-start"]'),
    ).not.toBeNull();
    fireEvent.click(remove);
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: t.confirmDeleteAction }),
    );
    if (kind === "resume")
      expect(props.resume.onBulkDeleteResumes).toHaveBeenCalledExactlyOnceWith([
        "resume-0",
        "resume-1",
      ]);
    else
      await waitFor(() =>
        expect(
          props.template.onDeleteTemplates,
        ).toHaveBeenCalledExactlyOnceWith(["custom-a", "custom-b"]),
      );
    await waitFor(() => {
      expect(bulk.getAttribute("data-state")).toBe("closed");
      expect(bulk.hasAttribute("inert")).toBe(true);
      expect(bulk.style.gridTemplateColumns).toBe("0fr");
      expect(
        container.querySelector('[data-slot="badge"][aria-live="polite"]'),
      ).toBeNull();
    });
    expect(props.resume.onOpenResume).not.toHaveBeenCalled();
    expect(props.template.onOpenTemplate).not.toHaveBeenCalled();
  },
);
it.each(["resume", "template"] as const)(
  "distinguishes empty %s collections from unmatched search inside one surface",
  async (kind) => {
    const props = fixtures();
    const view = (empty: boolean) => (
      <MemoryRouter>
        {kind === "resume" ? (
          <ResumeGallery
            {...props.resume}
            resumes={empty ? [] : props.resume.resumes}
          />
        ) : (
          <TemplateGallery
            {...props.template}
            templates={empty ? [] : props.template.templates}
          />
        )}
      </MemoryRouter>
    );
    const { container, rerender } = render(view(true));
    assertFlatEmpty(
      container,
      kind === "resume" ? t.emptyResumes : t.emptyTemplates,
    );
    rerender(view(false));
    fireEvent.change(
      screen.getByRole("textbox", {
        name: kind === "resume" ? t.searchResumesLabel : t.searchTemplatesLabel,
      }),
      { target: { value: "no-such-card" } },
    );
    await waitFor(() =>
      assertFlatEmpty(
        container,
        kind === "resume" ? t.emptyResumeSearch : t.emptyTemplateSearch,
      ),
    );
  },
);
it("allows selection mode with only built-ins without selecting or deleting them", () => {
  const props = fixtures().template;
  props.templates = props.templates.map((item) => ({
    ...item,
    isBuiltIn: true,
  }));
  const { container } = render(
    <MemoryRouter>
      <TemplateGallery {...props} />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: t.selectItems }));
  expect(
    screen.getByRole("button", { name: t.cancelSelection }),
  ).not.toBeNull();
  const builtin = screen.getByRole("link", { name: "Template 0" });
  fireEvent.click(builtin);
  fireEvent.keyDown(builtin, { key: " " });
  expect(
    container.querySelector('[data-slot="badge"][aria-live="polite"]'),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: t.bulkDelete })).toBeNull();
  expect(props.onDeleteTemplates).not.toHaveBeenCalled();
  expect(props.onOpenTemplate).not.toHaveBeenCalled();
});
it.each(["resume", "template"] as const)(
  "leaves modified %s card clicks to native links",
  (kind) => {
    const props = fixtures();
    const open = vi.fn(),
      preload = vi.fn(),
      select = vi.fn();
    render(
      <MemoryRouter>
        {kind === "resume" ? (
          <ResumeGalleryCard
            t={t}
            item={props.resume.resumes[0]}
            template={props.template.templates[0]}
            isSelecting={false}
            isSelected={false}
            isOpening={false}
            showDeleteAction={false}
            updatedAtFormatter={new Intl.DateTimeFormat("en")}
            onPreloadDetail={preload}
            onOpenResume={open}
            onRequestDelete={vi.fn()}
            onToggleSelected={select}
          />
        ) : (
          <TemplateGalleryCard
            t={t}
            previewMessages={t}
            previewResume={props.template.previewResumes!.earlyCareer}
            template={props.template.templates[0]}
            isSelecting={false}
            isSelected={false}
            isOpening={false}
            isDefaultTemplate={false}
            settingDefaultTemplateId={null}
            onPreloadDetail={preload}
            onOpenTemplate={open}
            onRequestDelete={vi.fn()}
            onSetDefaultTemplate={vi.fn()}
            onToggleSelected={select}
          />
        )}
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", {
      name: kind === "resume" ? "Resume 0" : "Template 0",
    });
    for (const modifier of [
      "metaKey",
      "ctrlKey",
      "altKey",
      "shiftKey",
    ] as const) {
      let prevented = true;
      document.addEventListener(
        "click",
        (event) => {
          prevented = event.defaultPrevented;
          event.preventDefault();
        },
        { once: true },
      );
      fireEvent(link, createEvent.click(link, { button: 0, [modifier]: true }));
      expect(prevented).toBe(false);
    }
    expect(open).not.toHaveBeenCalled();
    expect(select).not.toHaveBeenCalled();
    fireEvent.pointerEnter(link);
    fireEvent.focus(link);
    fireEvent.pointerDown(link);
    expect(preload).toHaveBeenCalledTimes(3);
    fireEvent.click(link);
    expect(open).toHaveBeenCalledExactlyOnceWith(
      kind === "resume" ? "resume-0" : "custom-a",
    );
  },
);
it("centers skeleton grid tracks with the same gallery sizing contract", () => {
  const { container } = render(<GalleryRouteSkeleton itemCount={2} />);
  const grid = Array.from(container.querySelectorAll("div")).find((element) =>
    element.classList.contains(
      "grid-cols-[repeat(auto-fill,minmax(208px,228px))]",
    ),
  )!;
  expect(grid).toBeTruthy();
  expect(grid.classList.contains("justify-center")).toBe(true);
});

it("clamps resume controller pages, filters deleted selections and searches deferred content", () => {
  const resumes = Array.from({ length: 7 }, (_, i) =>
    createResumeDetailItem({ id: `resume-${i}`, title: `Resume ${i}` }),
  );
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={["/resume?page=99"]}>{children}</MemoryRouter>
  );
  const { result, rerender } = renderHook(
    ({ items }) =>
      useResumeGalleryController({
        locale: "en",
        resumes: items,
        pageSize: 2,
        onDeleteResume: vi.fn(),
        onBulkDeleteResumes: vi.fn(),
      }),
    { wrapper, initialProps: { items: resumes } },
  );
  expect(result.current.safeCurrentPage).toBe(4);
  expect(result.current.paginatedResumes.map(({ id }) => id)).toEqual([
    "resume-6",
  ]);
  act(() => {
    result.current.toggleSelecting();
    result.current.toggleSelected("resume-0");
    result.current.toggleSelected("missing");
  });
  expect(result.current.selectedResumeIds).toEqual(["resume-0"]);
  expect(result.current.selectedIdSet.has("resume-0")).toBe(true);
  rerender({ items: resumes.slice(1) });
  expect(result.current.selectedResumeIds).toEqual([]);
  act(() => result.current.setSearchQuery("  RESUME 3  "));
  expect(result.current.paginatedResumes.map(({ id }) => id)).toEqual([
    "resume-3",
  ]);
  expect(result.current.safeCurrentPage).toBe(1);
});
it("clamps template controller pages and excludes built-ins or removed IDs from selection", () => {
  const templates = Array.from({ length: 7 }, (_, i) =>
    createResumeDetailTemplate(`template-${i}`, {
      name: `Template ${i}`,
      isBuiltIn: i === 0,
    }),
  );
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={["/templates?page=99"]}>
      {children}
    </MemoryRouter>
  );
  const { result, rerender } = renderHook(
    ({ items }) =>
      useTemplateGalleryController({
        templates: items,
        pageSize: 2,
        onDeleteTemplates: vi.fn(async (ids: string[]) => ids),
      }),
    { wrapper, initialProps: { items: templates } },
  );
  expect(result.current.safeCurrentPage).toBe(4);
  expect(result.current.paginatedTemplates.map(({ id }) => id)).toEqual([
    "template-6",
  ]);
  act(() => {
    result.current.toggleSelecting();
    result.current.toggleSelected("template-0");
    result.current.toggleSelected("template-1");
    result.current.toggleSelected("missing");
  });
  expect(result.current.selectedTemplateIds).toEqual(["template-1"]);
  expect(result.current.selectedIdSet.has("template-0")).toBe(false);
  rerender({ items: templates.slice(2) });
  expect(result.current.selectedTemplateIds).toEqual([]);
  act(() => result.current.setSearchQuery("  TEMPLATE 3  "));
  expect(result.current.paginatedTemplates.map(({ id }) => id)).toEqual([
    "template-3",
  ]);
  expect(result.current.safeCurrentPage).toBe(1);
});
