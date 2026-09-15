import { toast } from "sonner";

let activeToastId: string | number | undefined;

function forgetToast({ id }: { id: string | number }) {
  if (activeToastId === id) {
    activeToastId = undefined;
  }
}

export function clearWorkspaceNavigationError() {
  const id = activeToastId;
  activeToastId = undefined;
  if (id !== undefined) {
    toast.dismiss(id);
  }
}

export function showWorkspaceNavigationError(message: string) {
  const id = toast.getToasts().some((item) => item.id === activeToastId)
    ? activeToastId
    : undefined;
  activeToastId = toast.error(message, {
    closeButton: true,
    id,
    onDismiss: forgetToast,
    onAutoClose: forgetToast,
  });
}
