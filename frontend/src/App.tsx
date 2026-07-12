import { Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import {
  clearAuthSession,
  isAuthRequired,
  loadAuthSession,
  loginWithCredentials,
  refreshAuthSession,
} from "@/lib/auth";
import { isApiErrorToastShown } from "@/lib/api-client";
import {
  defaultMessages,
  getMessagesSync,
  getSystemLocale,
  loadMessages,
  type AppMessages,
  type Locale,
} from "@/i18n";
import {
  loadLocalePreferenceApi,
  saveLocalePreferenceApi,
} from "@/lib/preference-api";
import { runViewTransition } from "@/lib/view-transition";
import { Skeleton } from "@/components/ui/skeleton";
import { ViewTransitionBoundary } from "@/components/view-transition";

const LoginPage = lazy(() =>
  import("@/components/auth/login-page").then((module) => ({
    default: module.LoginPage,
  })),
);
const ResumeBuilder = lazy(() =>
  import("@/components/resume-builder").then((module) => ({
    default: module.ResumeBuilder,
  })),
);
const PdfExportRenderer = lazy(() =>
  import("@/components/pdf-export-renderer").then((module) => ({
    default: module.PdfExportRenderer,
  })),
);

function getInitialLocale(isAuthenticated: boolean) {
  return isAuthenticated
    ? (loadLocalePreferenceApi() ?? getSystemLocale())
    : getSystemLocale();
}

function AppRouteFallback() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-6">
      <div className="w-[min(420px,100%)] space-y-5">
        <div className="flex items-center gap-3">
          <Skeleton className="size-12 rounded-2xl" />
          <div className="grid flex-1 gap-2">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-3 w-48" />
          </div>
        </div>
        <div className="rounded-3xl border border-border bg-card p-5 shadow-sm">
          <div className="grid gap-3">
            <Skeleton className="h-11 w-full rounded-2xl" />
            <Skeleton className="h-11 w-full rounded-2xl" />
            <Skeleton className="h-11 w-36 rounded-2xl" />
          </div>
        </div>
      </div>
    </div>
  );
}

function AppRouteSuspense({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <ViewTransitionBoundary exit="slide-down">
          <AppRouteFallback />
        </ViewTransitionBoundary>
      }
    >
      <ViewTransitionBoundary enter="slide-up" default="none">
        {children}
      </ViewTransitionBoundary>
    </Suspense>
  );
}

function App() {
  const authRequired = isAuthRequired();
  const [isAuthenticated, setIsAuthenticated] = useState(() =>
    authRequired ? loadAuthSession() : true,
  );
  const [locale, setLocale] = useState<Locale>(() =>
    getInitialLocale(isAuthenticated),
  );
  const [messages, setMessages] = useState<AppMessages>(() =>
    getMessagesSync(getInitialLocale(isAuthenticated)),
  );

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }

    saveLocalePreferenceApi(locale);
  }, [isAuthenticated, locale]);

  useEffect(() => {
    if (!authRequired || !isAuthenticated) {
      return;
    }

    const refreshInterval = window.setInterval(() => {
      void refreshAuthSession().catch((error) => {
        console.error("Failed to refresh auth session.", error);
        clearAuthSession();
        setIsAuthenticated(false);
      });
    }, 4 * 60 * 60 * 1000);

    return () => {
      window.clearInterval(refreshInterval);
    };
  }, [authRequired, isAuthenticated]);

  useEffect(() => {
    let cancelled = false;

    void loadMessages(locale)
      .then((nextMessages) => {
        if (!cancelled) {
          setMessages(nextMessages);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMessages(defaultMessages);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [locale]);

  async function handleLogin(credentials: {
    username: string;
    password: string;
  }) {
    try {
      await loginWithCredentials(credentials.username, credentials.password);

      runViewTransition(() => {
        setLocale(loadLocalePreferenceApi() ?? getSystemLocale());
        setIsAuthenticated(true);
      }, "nav-forward");

      return {
        ok: true as const,
      };
    } catch (error) {
      return {
        ok: false as const,
        error: error instanceof Error ? error.message : messages.loginInvalidCredentials,
        errorShown: isApiErrorToastShown(error),
      };
    }
  }

  function handleLogout() {
    clearAuthSession();
    runViewTransition(() => {
      setLocale(getSystemLocale());
      setIsAuthenticated(!authRequired);
    }, "nav-back");
  }

  const renderLoginPage = () => (
    <AppRouteSuspense>
      <LoginPage t={messages} onSubmitCredentials={handleLogin} />
    </AppRouteSuspense>
  );

  const renderResumeBuilder = () => (
    <AppRouteSuspense>
      <ResumeBuilder
        locale={locale}
        messages={messages}
        onLocaleChange={setLocale}
        onLogout={handleLogout}
      />
    </AppRouteSuspense>
  );
  const renderPdfExport = () => (
    <AppRouteSuspense>
      <PdfExportRenderer />
    </AppRouteSuspense>
  );

  if (authRequired && !isAuthenticated) {
    return (
      <BrowserRouter>
        <Routes>
          <Route path="/pdf-export" element={renderPdfExport()} />
          <Route path="/login" element={renderLoginPage()} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/pdf-export" element={renderPdfExport()} />
        <Route path="/resume" element={renderResumeBuilder()} />
        <Route path="/resume/:id" element={renderResumeBuilder()} />
        <Route path="/templates" element={renderResumeBuilder()} />
        <Route path="/template/:id" element={renderResumeBuilder()} />
        <Route path="/trash" element={renderResumeBuilder()} />
        <Route path="/models" element={renderResumeBuilder()} />
        <Route path="/settings" element={renderResumeBuilder()} />
        <Route path="/login" element={<Navigate to="/resume" replace />} />
        <Route path="*" element={<Navigate to="/resume" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
