import { Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import {
  clearAuthSession,
  isAuthRequired,
  loadAuthSession,
  loginWithCredentials,
  refreshAuthSession,
} from "@/lib/auth";
import { isApiErrorToastShown } from "@/lib/api-client";
import {
  getSystemLocale,
  type AppMessages,
  type Locale,
} from "@/i18n";
import { useLocaleMessages } from "@/i18n/use-locale-messages";
import {
  loadLocalePreferenceApi,
  saveLocalePreferenceApi,
} from "@/lib/preference-api";
import { createWorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import { runViewTransition } from "@/lib/view-transition";
import { Skeleton } from "@/components/ui/skeleton";
import { ViewTransitionBoundary } from "@/components/view-transition";

const loadLoginPage = () =>
  import("@/components/auth/login-page").then((module) => ({
    default: module.LoginPage,
  }));
const loadResumeGalleryWorkspacePage = () =>
  import("@/components/workspace/resume-gallery-workspace-page").then(
    (module) => ({ default: module.ResumeGalleryWorkspacePage }),
  );
const loadResumeDetailWorkspacePage = () =>
  import("@/components/workspace/resume-detail-workspace-page").then(
    (module) => ({ default: module.ResumeDetailWorkspacePage }),
  );
const loadModelsWorkspacePage = () =>
  import("@/components/workspace/models-workspace-page").then((module) => ({
    default: module.ModelsWorkspacePage,
  }));
const loadSettingsWorkspacePage = () =>
  import("@/components/workspace/settings-workspace-page").then((module) => ({
    default: module.SettingsWorkspacePage,
  }));
const loadTemplateGalleryWorkspacePage = () =>
  import("@/components/workspace/template-gallery-workspace-page").then(
    (module) => ({ default: module.TemplateGalleryWorkspacePage }),
  );
const loadTemplateDetailWorkspacePage = () =>
  import("@/components/workspace/template-detail-workspace-page").then(
    (module) => ({ default: module.TemplateDetailWorkspacePage }),
  );
const loadTrashWorkspacePage = () =>
  import("@/components/workspace/trash-workspace-page").then((module) => ({
    default: module.TrashWorkspacePage,
  }));
const loadPdfExportRenderer = () =>
  import("@/components/pdf-export-renderer").then((module) => ({
    default: module.PdfExportRenderer,
  }));
const LoginPage = lazy(loadLoginPage);
const ResumeGalleryWorkspacePage = lazy(loadResumeGalleryWorkspacePage);
const ResumeDetailWorkspacePage = lazy(loadResumeDetailWorkspacePage);
const ModelsWorkspacePage = lazy(loadModelsWorkspacePage);
const SettingsWorkspacePage = lazy(loadSettingsWorkspacePage);
const TemplateGalleryWorkspacePage = lazy(loadTemplateGalleryWorkspacePage);
const TemplateDetailWorkspacePage = lazy(loadTemplateDetailWorkspacePage);
const TrashWorkspacePage = lazy(loadTrashWorkspacePage);
const PdfExportRenderer = lazy(loadPdfExportRenderer);

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

function DocumentMetadata({
  locale,
  messages,
}: {
  locale: Locale;
  messages: AppMessages;
}) {
  const { pathname } = useLocation();

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";

    const pageLabel = pathname.startsWith("/resume")
      ? messages.myResume
      : pathname.startsWith("/template")
        ? messages.resumeTemplates
        : pathname === "/trash"
          ? messages.recycleBin
          : pathname === "/models"
            ? messages.modelSettings
            : pathname === "/settings"
              ? messages.settings
              : null;

    document.title = pageLabel
      ? `${pageLabel} · ${messages.brandTitle}`
      : pathname === "/login"
        ? messages.loginTitle
        : messages.brandTitle;
  }, [locale, messages, pathname]);

  return null;
}

function App() {
  const { pathname } = useLocation();
  const authRequired = isAuthRequired();
  const [isAuthenticated, setIsAuthenticated] = useState(() =>
    authRequired ? loadAuthSession() : true,
  );
  const [initialLocale] = useState(() => getInitialLocale(isAuthenticated));
  const [preferencesPersistence] = useState(() =>
    createWorkspacePreferencesPersistence(),
  );
  const {
    canPersistLocale,
    changeLocale,
    isMessagesReady,
    locale,
    messages,
  } = useLocaleMessages(initialLocale);

  useEffect(() => {
    if (isMessagesReady) {
      return;
    }

    const routeRequest =
      pathname === "/pdf-export"
        ? loadPdfExportRenderer
        : authRequired && !isAuthenticated
          ? loadLoginPage
          : pathname === "/models"
            ? loadModelsWorkspacePage
            : pathname === "/settings"
              ? loadSettingsWorkspacePage
              : pathname === "/templates"
                ? loadTemplateGalleryWorkspacePage
                : pathname.startsWith("/template/")
                  ? loadTemplateDetailWorkspacePage
                : pathname === "/trash"
                  ? loadTrashWorkspacePage
                  : pathname === "/resume"
                    ? loadResumeGalleryWorkspacePage
                    : pathname.startsWith("/resume/")
                      ? loadResumeDetailWorkspacePage
                      : loadResumeGalleryWorkspacePage;

    // Start the route request in the same commit as the locale request so a
    // saved non-default language never creates a locale-to-route waterfall.
    void routeRequest().catch((error: unknown) => {
      console.error("Failed to preload the current application route.", error);
    });
  }, [authRequired, isAuthenticated, isMessagesReady, pathname]);

  useEffect(() => {
    if (!isAuthenticated || !canPersistLocale) {
      return;
    }

    saveLocalePreferenceApi(locale);
  }, [canPersistLocale, isAuthenticated, locale]);

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

  async function handleLogin(credentials: {
    username: string;
    password: string;
  }) {
    try {
      await loginWithCredentials(credentials.username, credentials.password);

      runViewTransition(() => {
        changeLocale(loadLocalePreferenceApi() ?? getSystemLocale());
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
      changeLocale(getSystemLocale());
      setIsAuthenticated(!authRequired);
    }, "nav-back");
  }

  const renderLoginPage = () => (
    <AppRouteSuspense>
      <LoginPage t={messages} onSubmitCredentials={handleLogin} />
    </AppRouteSuspense>
  );

  const renderResumeGalleryWorkspace = () => (
    <AppRouteSuspense>
      <ResumeGalleryWorkspacePage
        locale={locale}
        messages={messages}
        onLocaleChange={changeLocale}
        onLogout={handleLogout}
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderResumeDetailWorkspace = () => (
    <AppRouteSuspense>
      <ResumeDetailWorkspacePage
        locale={locale}
        messages={messages}
        onLocaleChange={changeLocale}
        onLogout={handleLogout}
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderModelsWorkspace = () => (
    <AppRouteSuspense>
      <ModelsWorkspacePage
        locale={locale}
        messages={messages}
        onLocaleChange={changeLocale}
        onLogout={handleLogout}
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderSettingsWorkspace = () => (
    <AppRouteSuspense>
      <SettingsWorkspacePage
        locale={locale}
        messages={messages}
        onLocaleChange={changeLocale}
        onLogout={handleLogout}
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderTemplateGalleryWorkspace = () => (
    <AppRouteSuspense>
      <TemplateGalleryWorkspacePage
        locale={locale}
        messages={messages}
        onLocaleChange={changeLocale}
        onLogout={handleLogout}
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderTemplateDetailWorkspace = () => (
    <AppRouteSuspense>
      <TemplateDetailWorkspacePage
        locale={locale}
        messages={messages}
        onLocaleChange={changeLocale}
        onLogout={handleLogout}
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderTrashWorkspace = () => (
    <AppRouteSuspense>
      <TrashWorkspacePage
        locale={locale}
        messages={messages}
        onLocaleChange={changeLocale}
        onLogout={handleLogout}
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderPdfExport = () => (
    <AppRouteSuspense>
      <PdfExportRenderer />
    </AppRouteSuspense>
  );

  if (!isMessagesReady) {
    return <AppRouteFallback />;
  }

  if (authRequired && !isAuthenticated) {
    return (
      <>
        <DocumentMetadata locale={locale} messages={messages} />
        <Routes>
          <Route path="/pdf-export" element={renderPdfExport()} />
          <Route path="/login" element={renderLoginPage()} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </>
    );
  }

  return (
    <>
      <DocumentMetadata locale={locale} messages={messages} />
      <Routes>
        <Route path="/pdf-export" element={renderPdfExport()} />
        <Route path="/resume" element={renderResumeGalleryWorkspace()} />
        <Route path="/resume/:id" element={renderResumeDetailWorkspace()} />
        <Route path="/models" element={renderModelsWorkspace()} />
        <Route path="/settings" element={renderSettingsWorkspace()} />
        <Route path="/templates" element={renderTemplateGalleryWorkspace()} />
        <Route path="/template/:id" element={renderTemplateDetailWorkspace()} />
        <Route path="/trash" element={renderTrashWorkspace()} />
        <Route path="/login" element={<Navigate to="/resume" replace />} />
        <Route path="*" element={<Navigate to="/resume" replace />} />
      </Routes>
    </>
  );
}

export default App;
