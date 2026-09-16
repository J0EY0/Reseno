import { createRoot } from "react-dom/client";

import { ResumePreview } from "@/components/preview/resume-preview";
import { loadMessages } from "@/i18n";
import { waitForPdfImport } from "@/lib/pdf-resume-import/abort";
import {
  fitResumeToOnePage,
  type SmartOnePageStyleSnapshot,
} from "@/lib/smart-one-page";
import {
  createTemplateSettings,
  getTemplateById,
  getTemplateCatalog,
} from "@/lib/templates";
import { fetchWorkspaceRouteData } from "@/lib/workspace-api";
import type { DocumentLocale, ResumeData } from "@/types/resume";

export async function fitImportedResumeToOnePage(
  resume: ResumeData,
  documentLocale: DocumentLocale,
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  const [messages, { data }] = await waitForPdfImport(
    Promise.all([
      loadMessages(documentLocale),
      fetchWorkspaceRouteData("template-gallery", {
        signal,
        notifyOnError: false,
      }),
    ]),
    signal,
  );
  const template = getTemplateById(
    getTemplateCatalog(messages, data.customTemplates),
    data.defaultTemplateIds[documentLocale],
  );
  const original: SmartOnePageStyleSnapshot = {
    typography: template.typography,
    templateSettings: null,
  };
  let candidate = original;
  let renderKey = 0;
  let rejectRender: (error: unknown) => void = () => {};
  const host = document.createElement("div");
  host.inert = true;
  host.setAttribute("aria-hidden", "true");
  host.style.cssText =
    "position:fixed;left:-10000px;top:0;visibility:hidden;pointer-events:none;";
  document.body.append(host);
  const root = createRoot(host, {
    onUncaughtError: (error) => rejectRender(error),
  });

  try {
    const result = await fitResumeToOnePage(original, template.settings, {
      applyStyle(style) {
        signal?.throwIfAborted();
        candidate = style;
      },
      measurePageCount() {
        signal?.throwIfAborted();
        return waitForPdfImport(
          new Promise<number>((resolve, reject) => {
            rejectRender = reject;
            root.render(
              <ResumePreview
                key={++renderKey}
                resume={resume}
                t={messages}
                fontFamily={candidate.typography.fontFamily}
                fontSize={candidate.typography.fontSize}
                template={{
                  ...template,
                  settings: createTemplateSettings(template.preset, {
                    ...template.settings,
                    ...candidate.templateSettings,
                  }),
                }}
                onPaginationReadyChange={(ready, count) => {
                  if (ready) resolve(count);
                }}
              />,
            );
          }),
          signal,
        );
      },
    });
    signal?.throwIfAborted();
    return {
      template: template.id,
      ...(result.status === "applied" ? result.style : original),
    };
  } finally {
    root.unmount();
    host.remove();
  }
}
