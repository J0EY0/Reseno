import { RefreshCw } from "lucide-react";

import type { AppMessages } from "@/i18n";

import { AuthPageShell } from "@/components/auth/auth-page-shell";
import { Button } from "@/components/ui/button";

export function AuthStatusErrorPage({
  onRetry,
  t,
}: {
  onRetry: () => void;
  t: AppMessages;
}) {
  return (
    <AuthPageShell
      brandTitle={t.brandTitle}
      formTitle={t.authStatusErrorFormTitle}
      description={t.authStatusErrorDescription}
    >
      <Button
        type="button"
        size="lg"
        className="h-11 rounded-xl"
        onClick={onRetry}
      >
        <RefreshCw data-icon="inline-start" />
        {t.retry}
      </Button>
    </AuthPageShell>
  );
}
