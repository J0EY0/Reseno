import { vi } from "vitest";
import { defaultMessages } from "@/i18n";
import { createTemplatePreviewResumes } from "@/lib/template-preview-resume";
import type { RecycleBinPanelProps } from "@/components/recycle-bin-types";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./resume-detail-fixtures";

export function createTrashProps(count = 7): RecycleBinPanelProps {
  const template = createResumeDetailTemplate("minimal");
  return {
    locale: "en",
    t: defaultMessages,
    deletedResumes: Array.from({ length: count }, (_, i) => ({
      ...createResumeDetailItem({
        id: `resume-${i}`,
        title: `Resume ${i}`,
        typography: { fontFamily: "serif", fontSize: 18 },
        templateSettings: { pageBackground: "#abcdef" },
      }),
      deletedAt: "2026-09-01T10:00:00.000Z",
    })),
    deletedTemplates: Array.from({ length: count }, (_, i) => ({
      ...createResumeDetailTemplate(`template-${i}`, { name: `Template ${i}` }),
      deletedAt: "2026-09-01T10:00:00.000Z",
    })),
    templates: [template],
    templatePreviewResumes: createTemplatePreviewResumes(defaultMessages),
    onRestoreResume: vi.fn(async () => true),
    onRestoreTemplate: vi.fn(async () => true),
    onDeleteResumeForever: vi.fn(async () => true),
    onDeleteTemplateForever: vi.fn(async () => true),
  };
}

export function installPanelBrowserApis() {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const original = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "scrollIntoView",
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
  return () => {
    if (original)
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", original);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  };
}
