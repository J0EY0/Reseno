import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ResumePreview } from "@/components/preview/resume-preview";
import {
  defaultMessages,
  getMessagesSync,
  loadMessages,
  type AppMessages,
  type Locale,
} from "@/i18n";
import {
  createTemplateSettings,
  getTemplateById,
  getTemplateCatalog,
} from "@/lib/templates";
import { isAbortError } from "@/lib/api-client";
import {
  fetchResumeApi,
  fetchResumeVersionApi,
  fetchWorkspaceRouteData,
} from "@/lib/workspace-api";
import type {
  ResumeTemplateDefinition,
  ResumeTypographySettings,
  ResumeWorkspaceItem,
} from "@/types/resume";

declare global {
  interface Window {
    __RESUMATE_PDF_READY__?: boolean;
    __RESUMATE_PDF_ERROR__?: string;
  }
}

interface PdfExportState {
  loadKey: string;
  messages: AppMessages;
  locale: Locale;
  resumeItem: ResumeWorkspaceItem;
  template: ResumeTemplateDefinition;
  typography: ResumeTypographySettings;
}

interface PdfExportError {
  loadKey: string;
  message: string;
}

function resolveLocale(value: string | null): Locale {
  return value === "en" || value === "zh" ? value : "zh";
}

async function waitForRenderAssets() {
  const delay = (milliseconds: number) =>
    new Promise<void>((resolve) => {
      window.setTimeout(resolve, milliseconds);
    });

  await Promise.race([document.fonts?.ready ?? Promise.resolve(), delay(2500)]);

  const images = Array.from(document.images);
  await Promise.race([
    Promise.all(
      images.map((image) => {
        if (image.complete) {
          return Promise.resolve();
        }

        return image.decode().catch(() => undefined);
      }),
    ),
    delay(2500),
  ]);

  await new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => resolve());
    });
  });
}

export function PdfExportRenderer() {
  const [searchParams] = useSearchParams();
  const locale = resolveLocale(searchParams.get("locale"));
  const resumeId = searchParams.get("resumeId") ?? "";
  const versionId = searchParams.get("versionId");
  const loadKey = `${locale}:${resumeId}:${versionId ?? "current"}`;
  const [state, setState] = useState<PdfExportState | null>(null);
  const [error, setError] = useState<PdfExportError | null>(null);
  const [assetsReadyLoadKey, setAssetsReadyLoadKey] = useState<string | null>(
    null,
  );
  const [paginationReadyLoadKey, setPaginationReadyLoadKey] = useState<
    string | null
  >(null);
  const initialMessages = useMemo(() => getMessagesSync(locale), [locale]);
  const activeState = state?.loadKey === loadKey ? state : null;
  const activeError = error?.loadKey === loadKey ? error.message : null;
  const isReady = Boolean(
    activeState &&
      assetsReadyLoadKey === loadKey &&
      paginationReadyLoadKey === loadKey,
  );

  const handlePaginationReadyChange = useCallback(
    (ready: boolean) => {
      setPaginationReadyLoadKey((current) => {
        if (ready) {
          return loadKey;
        }

        return current === loadKey ? null : current;
      });
    },
    [loadKey],
  );

  useEffect(() => {
    window.__RESUMATE_PDF_READY__ = false;
    window.__RESUMATE_PDF_ERROR__ = undefined;
  }, [loadKey]);

  useEffect(() => {
    window.__RESUMATE_PDF_READY__ = isReady;
  }, [isReady]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function loadExportData() {
      try {
        const [messages, result, resumeResult] = await Promise.all([
          loadMessages(locale).catch(() => defaultMessages),
          fetchWorkspaceRouteData("pdf-export", {
            signal: controller.signal,
          }),
          versionId
            ? fetchResumeVersionApi(resumeId, versionId, {
                signal: controller.signal,
              })
            : fetchResumeApi(resumeId, { signal: controller.signal }),
        ]);
        const workspace = result.data;
        const resumeItem = resumeResult.resume;

        const templateCatalog = getTemplateCatalog(
          messages,
          workspace.customTemplates,
        );
        const resolvedTemplate = getTemplateById(
          templateCatalog,
          resumeItem.template,
        );
        const template = {
          ...resolvedTemplate,
          // Export must resolve the same resume-level overrides as the editor;
          // otherwise PDF/PNG output can diverge from the visible preview.
          settings: createTemplateSettings(resolvedTemplate.preset, {
            ...resolvedTemplate.settings,
            ...(resumeItem.templateSettings ?? {}),
          }),
        };

        if (!cancelled) {
          setState({
            loadKey,
            messages,
            locale,
            resumeItem,
            template,
            typography: resumeItem.typography,
          });
        }
      } catch (loadError) {
        if (isAbortError(loadError)) {
          return;
        }

        const message =
          loadError instanceof Error
            ? loadError.message
            : "Failed to load PDF export data.";

        if (!cancelled) {
          window.__RESUMATE_PDF_ERROR__ = message;
          setError({ loadKey, message });
        }
      }
    }

    // Avoid sending the development-only StrictMode preflight request. The
    // real effect still owns an AbortController for route/query changes.
    const loadTimer = window.setTimeout(() => {
      if (!controller.signal.aborted) {
        void loadExportData();
      }
    }, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [loadKey, locale, resumeId, versionId]);

  useEffect(() => {
    if (!activeState) {
      return;
    }

    let cancelled = false;

    void waitForRenderAssets().then(() => {
      if (!cancelled) {
        setAssetsReadyLoadKey(activeState.loadKey);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [activeState]);

  if (activeError) {
    return (
      <main
        className="pdf-export-page flex min-h-svh items-center justify-center bg-white p-8 text-sm text-red-600"
        data-pdf-ready="false"
      >
        {activeError}
      </main>
    );
  }

  if (!activeState) {
    return (
      <main
        className="pdf-export-page flex min-h-svh items-center justify-center bg-white p-8 text-sm text-muted-foreground"
        data-pdf-ready="false"
      >
        {initialMessages.loading}
      </main>
    );
  }

  return (
    <main
      className="pdf-export-page bg-white text-foreground"
      data-pdf-ready={isReady ? "true" : "false"}
    >
      <ResumePreview
        t={activeState.messages}
        resume={activeState.resumeItem.resume}
        fontFamily={activeState.typography.fontFamily}
        fontSize={activeState.typography.fontSize}
        template={activeState.template}
        onPaginationReadyChange={handlePaginationReadyChange}
      />
    </main>
  );
}
