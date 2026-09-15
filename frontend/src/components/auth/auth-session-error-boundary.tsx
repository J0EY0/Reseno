import type { ReactNode } from "react";
import { ErrorBoundary } from "react-error-boundary";

import type { AppMessages } from "@/i18n";
import { isDynamicImportFailure } from "@/lib/dynamic-import-recovery";

export function AuthSessionErrorBoundary({
  children,
  t,
}: {
  children: ReactNode;
  t: AppMessages;
}) {
  return (
    <ErrorBoundary
      fallbackRender={({ error }) => {
        if (!isDynamicImportFailure(error)) throw error;
        return (
          <section
            role="alert"
            className="fixed inset-x-4 bottom-4 z-50 mx-auto grid max-w-md gap-3 rounded-xl border border-border bg-card p-4 text-sm text-card-foreground shadow-lg"
          >
            <h2 className="font-semibold">{t.authSessionExpiredTitle}</h2>
            <p className="text-muted-foreground">
              {t.authSessionExpiredDescription}
            </p>
            <a
              href="/login"
              target="_blank"
              rel="noopener noreferrer"
              className="w-fit rounded-sm text-primary underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t.authSessionOtherLogin}
            </a>
          </section>
        );
      }}
    >
      {children}
    </ErrorBoundary>
  );
}
