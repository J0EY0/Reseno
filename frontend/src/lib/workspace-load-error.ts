import { toast } from "sonner";
import { notifyApiError } from "@/lib/api-error-notifier";

let activeToastId: string | number | undefined;

export function dismissWorkspaceLoadError() {
  if (activeToastId !== undefined) {
    toast.dismiss(activeToastId);
    activeToastId = undefined;
  }
}

export function showWorkspaceLoadError(error: unknown, message: string) {
  notifyApiError(error, message, (text) => {
    dismissWorkspaceLoadError();
    activeToastId = toast.error(text, { closeButton: true });
  });
}
