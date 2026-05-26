import { Clock3, Trash2 } from "lucide-react";
import { useState } from "react";

import type { AppMessages, Locale } from "@/i18n";
import type {
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
} from "@/types/resume";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function formatAt(locale: Locale, value: string) {
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

type PendingTrashAction =
  | { type: "resume-item"; ids: string[] }
  | { type: "template-item"; ids: string[] }
  | { type: "resume-empty" }
  | { type: "template-empty" }
  | null;

export function RecycleBinPanel({
  locale,
  t,
  deletedResumes,
  deletedTemplates,
  onRestoreResume,
  onDeleteResumeForever,
  onEmptyResumeTrash,
  onRestoreTemplate,
  onDeleteTemplateForever,
  onEmptyTemplateTrash,
}: {
  locale: Locale;
  t: AppMessages;
  deletedResumes: DeletedResumeWorkspaceItem[];
  deletedTemplates: DeletedResumeTemplateDefinition[];
  onRestoreResume: (resumeIds: string[]) => void;
  onDeleteResumeForever: (resumeIds: string[]) => void;
  onEmptyResumeTrash: () => void;
  onRestoreTemplate: (templateIds: string[]) => void;
  onDeleteTemplateForever: (templateIds: string[]) => void;
  onEmptyTemplateTrash: () => void;
}) {
  const [activeTab, setActiveTab] = useState<"resumes" | "templates">("resumes");
  const [pendingAction, setPendingAction] = useState<PendingTrashAction>(null);

  const isDialogOpen = Boolean(pendingAction);

  function closeDialog() {
    setPendingAction(null);
  }

  function confirmAction() {
    if (!pendingAction) {
      return;
    }

    if (pendingAction.type === "resume-item") {
      onDeleteResumeForever(pendingAction.ids);
    } else if (pendingAction.type === "template-item") {
      onDeleteTemplateForever(pendingAction.ids);
    } else if (pendingAction.type === "resume-empty") {
      onEmptyResumeTrash();
    } else if (pendingAction.type === "template-empty") {
      onEmptyTemplateTrash();
    }

    closeDialog();
  }

  const dialogTitle =
    pendingAction?.type === "resume-item"
      ? t.confirmDeleteResumeForeverTitle
      : pendingAction?.type === "template-item"
        ? t.confirmDeleteTemplateForeverTitle
        : pendingAction?.type === "resume-empty"
          ? t.confirmEmptyResumeTrashTitle
          : pendingAction?.type === "template-empty"
            ? t.confirmEmptyTemplateTrashTitle
            : "";

  const dialogDescription =
    pendingAction?.type === "resume-item"
      ? t.confirmDeleteResumeForeverDescription
      : pendingAction?.type === "template-item"
        ? t.confirmDeleteTemplateForeverDescription
        : pendingAction?.type === "resume-empty"
          ? t.confirmEmptyResumeTrashDescription
          : pendingAction?.type === "template-empty"
            ? t.confirmEmptyTemplateTrashDescription
            : "";

  const dialogActionLabel =
    pendingAction?.type === "resume-empty" || pendingAction?.type === "template-empty"
      ? t.emptyTrash
      : t.deleteForever;

  return (
    <main className="flex-1 p-4">
      <ConfirmActionDialog
        open={isDialogOpen}
        title={dialogTitle}
        description={dialogDescription}
        confirmLabel={dialogActionLabel}
        cancelLabel={t.cancel}
        onConfirm={confirmAction}
        onOpenChange={(open) => {
          if (!open) {
            closeDialog();
          }
        }}
      />

      <section className="grid gap-4">
      <Card className="rounded-[30px] border-border/70 bg-gradient-to-br from-background via-background to-muted/20 shadow-sm">
        <CardContent className="p-4 sm:p-6">
          <Tabs
            value={activeTab}
            onValueChange={(value) =>
              setActiveTab(value as "resumes" | "templates")
              }
            >
              <TabsList className="h-12 rounded-2xl bg-muted/70 p-1">
                <TabsTrigger value="resumes">{t.resumeRecycleBin}</TabsTrigger>
                <TabsTrigger value="templates">{t.templateRecycleBin}</TabsTrigger>
              </TabsList>

              <TabsContent value="resumes" className="mt-5">
                <Card className="rounded-[28px] border-border/60 bg-background/80 shadow-[0_18px_50px_-38px_rgba(15,23,42,0.45)]">
                  <CardContent className="p-5 sm:p-6">
                    {deletedResumes.length > 0 ? (
                      <div className="mb-4 flex justify-end">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => setPendingAction({ type: "resume-empty" })}
                      >
                        <Trash2 className="size-4" />
                        {t.emptyTrash}
                      </Button>
                      </div>
                    ) : null}
                    {deletedResumes.length > 0 ? (
                      <div className="grid gap-3">
                        {deletedResumes.map((item) => (
                          <div
                            key={item.id}
                            className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/70 bg-muted/20 px-4 py-3"
                          >
                            <div className="min-w-0">
                              <p className="truncate font-medium">
                                {item.title ||
                                  item.resume.basic.name ||
                                  t.untitledResume}
                              </p>
                              <p className="mt-1 truncate text-xs text-muted-foreground">
                                {item.resume.basic.headline ||
                                  item.resume.basic.email ||
                                  item.resume.basic.phone}
                              </p>
                              <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                                <Clock3 className="size-3" />
                                {formatAt(locale, item.deletedAt)}
                              </p>
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => onRestoreResume([item.id])}
                              >
                                {t.restore}
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                className="border border-red-600 bg-red-600 text-white hover:bg-red-600/90"
                                onClick={() =>
                                  setPendingAction({
                                    type: "resume-item",
                                    ids: [item.id],
                                  })
                                }
                              >
                                <Trash2 className="size-4" />
                                {t.deleteForever}
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex min-h-[220px] flex-col items-center justify-center text-center">
                        <div className="flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
                          <Trash2 className="size-5" />
                        </div>
                        <p className="mt-4 text-sm font-medium text-muted-foreground">
                          {t.emptyResumeTrash}
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="templates" className="mt-5">
                <Card className="rounded-[28px] border-border/60 bg-background/80 shadow-[0_18px_50px_-38px_rgba(15,23,42,0.45)]">
                  <CardContent className="p-5 sm:p-6">
                    {deletedTemplates.length > 0 ? (
                      <div className="mb-4 flex justify-end">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => setPendingAction({ type: "template-empty" })}
                      >
                        <Trash2 className="size-4" />
                        {t.emptyTrash}
                      </Button>
                      </div>
                    ) : null}
                    {deletedTemplates.length > 0 ? (
                      <div className="grid gap-3">
                        {deletedTemplates.map((item) => (
                          <div
                            key={item.id}
                            className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/70 bg-muted/20 px-4 py-3"
                          >
                            <div className="min-w-0">
                              <p className="truncate font-medium">{item.name}</p>
                              <p className="mt-1 truncate text-xs text-muted-foreground">
                                {item.description || t.templateDescriptionFallback}
                              </p>
                              <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                                <Clock3 className="size-3" />
                                {formatAt(locale, item.deletedAt)}
                              </p>
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => onRestoreTemplate([item.id])}
                              >
                                {t.restore}
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                className="border border-red-600 bg-red-600 text-white hover:bg-red-600/90"
                                onClick={() =>
                                  setPendingAction({
                                    type: "template-item",
                                    ids: [item.id],
                                  })
                                }
                              >
                                <Trash2 className="size-4" />
                                {t.deleteForever}
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex min-h-[220px] flex-col items-center justify-center text-center">
                        <div className="flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
                          <Trash2 className="size-5" />
                        </div>
                        <p className="mt-4 text-sm font-medium text-muted-foreground">
                          {t.emptyTemplateTrash}
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </section>
    </main>
  );
}
