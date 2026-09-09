import { useEffect, useState } from "react";
import { useRouteError } from "react-router-dom";

import {
  defaultLocale,
  getLoadedMessages,
  getMessagesSync,
  getSystemLocale,
} from "@/i18n";
import { loadLocalePreferenceApi } from "@/lib/preference-api";

import {
  getApplicationRouteErrorDetails,
  tryReloadAfterDynamicImportFailure,
} from "@/lib/dynamic-import-recovery";

export function AppRouteErrorPage() {
  const error = useRouteError();
  const [locale] = useState(() => {
    let preferredLocale = getSystemLocale();
    try {
      preferredLocale = loadLocalePreferenceApi() ?? preferredLocale;
    } catch {
      return getLoadedMessages(preferredLocale)
        ? preferredLocale
        : defaultLocale;
    }
    return getLoadedMessages(preferredLocale) ? preferredLocale : defaultLocale;
  });
  const messages = getMessagesSync(locale);
  const details = getApplicationRouteErrorDetails(error);
  const isDynamicImportError = details.kind === "dynamic-import";

  useEffect(() => {
    console.error("Application route rendering failed.", error);
    if (isDynamicImportError) {
      tryReloadAfterDynamicImportFailure(error);
    }
  }, [error, isDynamicImportError]);

  return (
    <main
      lang={locale === "zh" ? "zh-CN" : "en"}
      className="flex min-h-svh w-screen items-center justify-center bg-background p-6"
    >
      <section
        role="alert"
        className="w-full max-w-md rounded-(--radius-card) border border-border bg-card p-8 text-center shadow-card"
      >
        <h1 className="text-xl font-semibold text-foreground">
          {isDynamicImportError
            ? messages.routeResourceLoadErrorTitle
            : messages.routeRuntimeErrorTitle}
        </h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {isDynamicImportError
            ? messages.routeResourceLoadErrorDescription
            : messages.routeRuntimeErrorDescription}
        </p>
        {details.message ? (
          <p className="mt-4 break-words rounded-lg bg-muted px-3 py-2 text-left font-mono text-xs leading-5 text-muted-foreground">
            {details.message}
          </p>
        ) : null}
        <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row sm:flex-wrap">
          {window.location.pathname !== "/resume" ? (
            <button
              type="button"
              className="inline-flex min-h-10 min-w-0 items-center justify-center whitespace-normal break-words rounded-md border border-border bg-background px-5 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              onClick={() => window.location.assign("/resume")}
            >
              {messages.backToResumes}
            </button>
          ) : null}
          <button
            type="button"
            className="inline-flex min-h-10 min-w-0 items-center justify-center whitespace-normal break-words rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            onClick={() => window.location.reload()}
          >
            {messages.reloadPage}
          </button>
        </div>
      </section>
    </main>
  );
}
