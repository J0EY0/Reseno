import { useContext, useRef, useState, type ReactNode } from "react";
import { ErrorBoundary } from "react-error-boundary";

import { ResourceRecoveryContext } from "@/components/resource-recovery-context";
import { Button } from "@/components/ui/button";
import { isDynamicImportFailure } from "@/lib/dynamic-import-recovery";
import { cn } from "@/lib/utils";

function ResourceLoadError({
  error,
  className,
}: {
  error: unknown;
  className?: string;
}) {
  const recovery = useContext(ResourceRecoveryContext);
  const request = useRef(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  if (!recovery || !isDynamicImportFailure(error)) {
    throw error;
  }

  async function recover() {
    if (request.current || !recovery) return;
    request.current = true;
    setIsSaving(true);
    setSaveFailed(false);
    try {
      await recovery.saveAndReload();
    } catch {
      setSaveFailed(true);
    } finally {
      request.current = false;
      setIsSaving(false);
    }
  }

  const { messages } = recovery;
  return (
    <div
      role="alert"
      className={cn("grid gap-3 rounded-md border p-4 text-sm", className)}
    >
      <p className="text-muted-foreground">
        {saveFailed
          ? messages.resourceRecoverySaveError
          : messages.resourceLoadError}
      </p>
      <Button
        type="button"
        variant="outline"
        className="w-fit whitespace-normal"
        disabled={isSaving}
        onClick={() => void recover()}
      >
        {isSaving ? messages.saving : messages.saveAndReload}
      </Button>
    </div>
  );
}

export function ResourceErrorBoundary({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <ErrorBoundary
      fallbackRender={({ error }) => (
        <ResourceLoadError error={error} className={className} />
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
