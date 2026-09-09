import { RefreshCw } from "lucide-react";

import type { AppMessages } from "@/i18n";

import { AuthPageShell } from "@/components/auth/auth-page-shell";
import { Button } from "@/components/ui/button";

export function AuthStatusErrorPage({
  onRetry,
  t,
  title,
  description,
}: {
  onRetry?: () => void;
  t: AppMessages;
  title?: string;
  description?: string;
}) {
  return (
    <AuthPageShell
      brandTitle={t.brandTitle}
      formTitle={title ?? t.authStatusErrorFormTitle}
      description={description ?? t.authStatusErrorDescription}
    >
      {onRetry ? (
        <div className="flex justify-center">
          <Button
            type="button"
            size="lg"
            className="h-11 rounded-xl"
            onClick={onRetry}
          >
            <RefreshCw data-icon="inline-start" />
            {t.retry}
          </Button>
        </div>
      ) : null}
    </AuthPageShell>
  );
}
