import { toast } from "sonner";

let activeToastId: string | number | undefined;

export function dismissWorkspaceLoadError() {
  if (activeToastId !== undefined) {
    toast.dismiss(activeToastId);
    activeToastId = undefined;
  }
}

export function showWorkspaceLoadError(message: string) {
  dismissWorkspaceLoadError();
  activeToastId = toast.error(message, { closeButton: true });
}
