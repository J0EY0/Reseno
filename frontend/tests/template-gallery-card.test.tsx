import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { defaultMessages as t } from "@/i18n";
import { TemplateGalleryCard } from "@/components/templates/template-gallery-card";
import { getBuiltInTemplates } from "@/lib/templates";
import { createTemplatePreviewResumes } from "@/lib/template-preview-resume";

const template = getBuiltInTemplates(t)[0];
const previewResume = createTemplatePreviewResumes(t).earlyCareer;
function props() {
  return {
    t,
    previewMessages: t,
    previewResume,
    template,
    isDefaultTemplate: false,
    isSelecting: false,
    isSelected: false,
    isOpening: false,
    settingDefaultTemplateId: null as string | null,
    onPreloadDetail: vi.fn(),
    onOpenTemplate: vi.fn(),
    onRequestDelete: vi.fn(),
    onSetDefaultTemplate: vi.fn(),
    onToggleSelected: vi.fn(),
  };
}

it("renders the real resume preview and preloads on pointer, focus and touch intent", () => {
  const value = props();
  const { container, rerender } = render(
    <MemoryRouter>
      <TemplateGalleryCard {...value} />
    </MemoryRouter>,
  );
  expect(
    container.querySelector('[data-export-root="resume-page"]')?.textContent,
  ).toContain(previewResume.basic.name);
  const card = screen.getByRole("link", { name: template.name });
  expect(card.getAttribute("href")).toBe(`/template/${template.id}`);
  fireEvent.pointerEnter(card);
  fireEvent.focus(card);
  fireEvent.pointerDown(card);
  expect(value.onPreloadDetail).toHaveBeenCalledTimes(3);
  fireEvent.click(card);
  expect(value.onOpenTemplate).toHaveBeenCalledExactlyOnceWith(template.id);
  rerender(
    <MemoryRouter>
      <TemplateGalleryCard {...value} isOpening />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: template.name })).toBe(card);
  expect(card.getAttribute("aria-busy")).toBe("true");
  expect(container.querySelector('[data-slot="spinner"]')).toBeNull();
});
it.each([false, true])(
  "only custom cards can be selected with pointer or Space, builtin=%s",
  (isBuiltIn) => {
    const value = {
      ...props(),
      template: { ...template, isBuiltIn },
      isSelecting: true,
      isSelected: true,
    };
    const { container } = render(
      <MemoryRouter>
        <TemplateGalleryCard {...value} />
      </MemoryRouter>,
    );
    const card = screen.getByRole(isBuiltIn ? "link" : "button", {
      name: template.name,
    });
    fireEvent.pointerEnter(card);
    fireEvent.focus(card);
    fireEvent.pointerDown(card);
    fireEvent.click(card);
    fireEvent.keyDown(card, { key: " " });
    expect(value.onPreloadDetail).not.toHaveBeenCalled();
    expect(value.onOpenTemplate).not.toHaveBeenCalled();
    expect(value.onToggleSelected).toHaveBeenCalledTimes(isBuiltIn ? 0 : 2);
    expect(card.getAttribute("aria-disabled")).toBe(String(isBuiltIn));
    expect(card.getAttribute("aria-pressed")).toBe(isBuiltIn ? null : "true");
    expect(card.tabIndex).toBe(isBuiltIn ? -1 : 0);
    const defaultButton = screen.getByRole("button", {
      name: t.setDefaultTemplate,
    });
    expect((defaultButton as HTMLButtonElement).disabled).toBe(true);
    expect(container.querySelectorAll(".border-primary").length > 0).toBe(
      !isBuiltIn,
    );
    if (isBuiltIn)
      expect(
        screen.queryByRole("button", { name: t.confirmDeleteAction }),
      ).toBeNull();
    else {
      fireEvent.click(
        screen.getByRole("button", { name: t.confirmDeleteAction }),
      );
      expect(value.onRequestDelete).toHaveBeenCalledExactlyOnceWith([
        template.id,
      ]);
    }
  },
);
it("retains stable default controls while updating or selecting", () => {
  const value = props();
  const { container, rerender } = render(
    <MemoryRouter>
      <TemplateGalleryCard {...value} />
    </MemoryRouter>,
  );
  const button = screen.getByRole("button", { name: t.setDefaultTemplate });
  fireEvent.click(button);
  expect(value.onSetDefaultTemplate).toHaveBeenCalledExactlyOnceWith(
    template.id,
  );
  rerender(
    <MemoryRouter>
      <TemplateGalleryCard {...value} settingDefaultTemplateId={template.id} />
    </MemoryRouter>,
  );
  expect(screen.getByRole("button", { name: t.setDefaultTemplate })).toBe(
    button,
  );
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(container.querySelector('[data-slot="spinner"]')).toBeNull();
  rerender(
    <MemoryRouter>
      <TemplateGalleryCard {...value} isDefaultTemplate isSelecting />
    </MemoryRouter>,
  );
  expect(screen.getByText(t.defaultTemplateLabel)).not.toBeNull();
  expect(
    screen.queryByRole("button", { name: t.setDefaultTemplate }),
  ).toBeNull();
});
