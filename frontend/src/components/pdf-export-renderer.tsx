import { useEffect, useMemo, useState } from "react";
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
  getTemplateById,
  getTemplateCatalog,
  normalizeCustomTemplates,
  normalizeDeletedTemplates,
} from "@/lib/templates";
import {
  fetchResumeApi,
  fetchResumeVersionApi,
  fetchWorkspaceBootstrap,
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
  messages: AppMessages;
  locale: Locale;
  resumeItem: ResumeWorkspaceItem;
  template: ResumeTemplateDefinition;
  typography: ResumeTypographySettings;
}

const defaultTypography: ResumeTypographySettings = {
  fontFamily: "inter",
  fontSize: 16,
};

function resolveLocale(value: string | null): Locale {
  return value === "en" || value === "zh" ? value : "zh";
}

function getResumeTemplateId(
  item: ResumeWorkspaceItem,
  defaultTemplateId: unknown,
) {
  if (typeof item.template === "string" && item.template.trim()) {
    return item.template;
  }

  return typeof defaultTemplateId === "string" && defaultTemplateId.trim()
    ? defaultTemplateId
    : "minimal";
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
  const [state, setState] = useState<PdfExportState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);
  const initialMessages = useMemo(() => getMessagesSync(locale), [locale]);

  useEffect(() => {
    setIsReady(false);
    window.__RESUMATE_PDF_READY__ = false;
    window.__RESUMATE_PDF_ERROR__ = undefined;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadExportData() {
      try {
        const [messages, result, resumeResult] = await Promise.all([
          loadMessages(locale).catch(() => defaultMessages),
          fetchWorkspaceBootstrap(locale),
          versionId
            ? fetchResumeVersionApi(resumeId, versionId)
            : fetchResumeApi(resumeId),
        ]);
        const workspace = result.workspace;
        const resumeItem = resumeResult.resume;

        const deletedTemplates = normalizeDeletedTemplates(workspace);
        const templateCatalog = getTemplateCatalog(
          messages,
          normalizeCustomTemplates(workspace),
          deletedTemplates.map((item) => item.id),
        );
        const template = getTemplateById(
          templateCatalog,
          getResumeTemplateId(resumeItem, workspace.defaultTemplateId),
          getResumeTemplateId(
            { ...resumeItem, template: undefined },
            workspace.defaultTemplateId,
          ),
        );

        if (!template) {
          throw new Error("Template not found.");
        }

        if (!cancelled) {
          setState({
            messages,
            locale,
            resumeItem,
            template,
            typography:
              resumeItem.typography ?? template.typography ?? defaultTypography,
          });
        }
      } catch (loadError) {
        const message =
          loadError instanceof Error
            ? loadError.message
            : "Failed to load PDF export data.";

        if (!cancelled) {
          window.__RESUMATE_PDF_ERROR__ = message;
          setError(message);
        }
      }
    }

    void loadExportData();

    return () => {
      cancelled = true;
    };
  }, [locale, resumeId, versionId]);

  useEffect(() => {
    if (!state) {
      return;
    }

    let cancelled = false;

    void waitForRenderAssets().then(() => {
      if (!cancelled) {
        window.__RESUMATE_PDF_READY__ = true;
        setIsReady(true);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [state]);

  if (error) {
    return (
      <main
        className="pdf-export-page flex min-h-svh items-center justify-center bg-white p-8 text-sm text-red-600"
        data-pdf-ready="false"
      >
        {error}
      </main>
    );
  }

  if (!state) {
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
        locale={state.locale}
        t={state.messages}
        resume={state.resumeItem.resume}
        fontFamily={state.typography.fontFamily}
        fontSize={state.typography.fontSize}
        template={state.template}
      />
    </main>
  );
}
