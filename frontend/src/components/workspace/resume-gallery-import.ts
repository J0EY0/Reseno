import { importResumePayload } from "@/lib/import-api";
import { normalizeResumeTitle } from "@/lib/resume-title";
import { createResumeApi, createTemplateApi } from "@/lib/workspace-api";
import type {
  ImportResumeResponse,
  ResumeCreateRequest,
  ResumeDetailResponse,
} from "@/types/api";
import type { ResumeTemplateDefinition } from "@/types/resume";

export interface ResumeImportOptions {
  signal?: AbortSignal;
  onResumeSaved?: (result: ResumeDetailResponse) => void;
  onTemplateSaved?: (template: ResumeTemplateDefinition) => void;
}

export interface ResumeImportResult {
  savedImports: ResumeDetailResponse[];
  importedCount: number;
  remainingCount: number;
  unclassifiedLineCount: number;
  retry: ((options: ResumeImportOptions) => Promise<ResumeImportResult>) | null;
}

interface ResumeImportBatch {
  templates: ImportResumeResponse["templates"];
  resumes: ResumeCreateRequest[];
  templateIds: Map<string, string>;
  importedCount: number;
  unclassifiedLineCount: number;
}

async function persistResumeImport(
  batch: ResumeImportBatch,
  options: ResumeImportOptions,
): Promise<ResumeImportResult> {
  const templates = batch.templates;
  batch.templates = [];
  for (const [index, item] of templates.entries()) {
    if (options.signal?.aborted) {
      batch.templates.push(...templates.slice(index));
      break;
    }
    let template: ResumeTemplateDefinition;
    try {
      const result = await createTemplateApi(item.definition, {
        notifyOnError: false,
      });
      template = result.template;
    } catch (error) {
      console.error("Failed to import embedded template.", error);
      batch.templates.push(item);
      continue;
    }
    batch.templateIds.set(item.ref, template.id);
    options.onTemplateSaved?.(template);
  }

  const resumes = batch.resumes;
  const savedImports: ResumeDetailResponse[] = [];
  batch.resumes = [];
  for (const [index, item] of resumes.entries()) {
    if (options.signal?.aborted) {
      batch.resumes.push(...resumes.slice(index));
      break;
    }
    const templateId = item.template && batch.templateIds.get(item.template);
    if (item.template?.startsWith("custom:") && !templateId) {
      batch.resumes.push(item);
      continue;
    }
    let result: ResumeDetailResponse;
    try {
      result = await createResumeApi(
        { ...item, ...(templateId ? { template: templateId } : {}) },
        { notifyOnError: false },
      );
    } catch (error) {
      console.error("Failed to import resume.", error);
      batch.resumes.push(item);
      continue;
    }
    batch.importedCount += 1;
    savedImports.push(result);
    options.onResumeSaved?.(result);
  }

  return {
    savedImports,
    importedCount: batch.importedCount,
    remainingCount: batch.resumes.length,
    unclassifiedLineCount: batch.unclassifiedLineCount,
    retry:
      batch.resumes.length > 0
        ? (nextOptions) => persistResumeImport(batch, nextOptions)
        : null,
  };
}

export async function importResumesIntoWorkspace(
  file: File,
  options: ResumeImportOptions = {},
): Promise<ResumeImportResult> {
  options.signal?.throwIfAborted();
  const batch: ResumeImportBatch = {
    templates: [],
    resumes: [],
    templateIds: new Map(),
    importedCount: 0,
    unclassifiedLineCount: 0,
  };
  const isPdfImport =
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (isPdfImport) {
    const { importResumeFromPdf } = await import("@/lib/pdf-resume-import");
    const { documentLocale, resume, unclassifiedLineCount } =
      await importResumeFromPdf(file, { signal: options.signal });
    batch.unclassifiedLineCount = unclassifiedLineCount;
    batch.resumes.push({
      documentLocale,
      jobBrief: "",
      resume,
      title: normalizeResumeTitle(
        file.name.replace(/\.pdf$/i, ""),
        documentLocale === "zh" ? "简历" : "Resume",
      ),
      templateSettings: null,
    });
  } else {
    const bundle = await importResumePayload(file, {
      signal: options.signal,
      notifyOnError: false,
    });
    batch.templates = bundle.templates;
    batch.resumes = bundle.resumes;
  }
  options.signal?.throwIfAborted();
  if (batch.resumes.length === 0) {
    throw new Error("No valid resume documents found in the imported file.");
  }
  return persistResumeImport(batch, options);
}
