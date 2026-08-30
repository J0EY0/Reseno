import type { AppMessages, Locale } from "@/i18n";
import type {
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ResumeData,
  ResumeTemplateDefinition,
  ResumeTypographySettings,
} from "@/types/resume";

export interface RecycleBinPanelProps {
  locale: Locale;
  t: AppMessages;
  deletedResumes: DeletedResumeWorkspaceItem[];
  deletedTemplates: DeletedResumeTemplateDefinition[];
  templates: ResumeTemplateDefinition[];
  templatePreviewResume: ResumeData;
  onRestoreResume: (resumeIds: string[]) => Promise<boolean>;
  onDeleteResumeForever: (resumeIds: string[]) => Promise<boolean>;
  onRestoreTemplate: (templateIds: string[]) => Promise<boolean>;
  onDeleteTemplateForever: (templateIds: string[]) => Promise<boolean>;
}

export type RecycleBinTab = "resumes" | "templates";

export type RecycleBinPreviewTarget =
  | {
      variant: "resume";
      title: string;
      resume: ResumeData;
      template: ResumeTemplateDefinition;
      typography: ResumeTypographySettings;
    }
  | {
      variant: "template";
      title: string;
      resume: ResumeData;
      template: ResumeTemplateDefinition;
    };

export type PendingTrashAction =
  | { type: "resume-item"; ids: string[] }
  | { type: "template-item"; ids: string[] }
  | null;

export type TrashActionKey =
  | `resume-restore:${string}`
  | `template-restore:${string}`
  | "resume-restore-selected"
  | "template-restore-selected"
  | "resume-delete"
  | "template-delete";
