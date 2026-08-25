import { Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import { loadAuthSession } from "@/lib/auth";
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
import { clearWorkspaceLateralRouteMemory } from "@/lib/workspace-route-memory";
import { useAuthGate } from "@/hooks/use-auth-gate";
import { Spinner } from "@/components/ui/spinner";
import { clearDynamicImportReloadGuard } from "@/lib/dynamic-import-recovery";

const loadAuthStatusErrorPage = () =>
  import("@/components/auth/auth-status-error-page").then((module) => ({
    default: module.AuthStatusErrorPage,
  }));
const loadLoginPage = () =>
  import("@/components/auth/login-page").then((module) => ({
    default: module.LoginPage,
  }));
const loadSetupPage = () =>
  import("@/components/auth/setup-page").then((module) => ({
    default: module.SetupPage,
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
const AuthStatusErrorPage = lazy(loadAuthStatusErrorPage);
const LoginPage = lazy(loadLoginPage);
const SetupPage = lazy(loadSetupPage);
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
    <div className="flex min-h-svh items-center justify-center bg-background">
      <Spinner className="size-8 text-muted-foreground" />
    </div>
  );
}

function DynamicImportRecoveryReset() {
  const { key } = useLocation();

  useEffect(() => {
    clearDynamicImportReloadGuard();
  }, [key]);

  return null;
}

function AppRouteSuspense({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<AppRouteFallback />}>
      {children}
      <DynamicImportRecoveryReset />
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
      : pathname === "/setup"
        ? messages.setupTitle
      : pathname === "/login"
        ? messages.loginTitle
        : messages.brandTitle;
  }, [locale, messages, pathname]);

  return null;
}

function App() {
  const { pathname } = useLocation();
  const [initialLocale] = useState(() =>
    getInitialLocale(loadAuthSession()),
  );
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
  const { authGate, login, logout, retry, setup } = useAuthGate({
    loginFallbackError: messages.loginInvalidCredentials,
    onAuthenticated: () => {
      changeLocale(loadLocalePreferenceApi() ?? getSystemLocale());
    },
    onLoggedOut: () => {
      changeLocale(getSystemLocale());
    },
    requestFallbackError: messages.apiMessages.REQUEST_FAILED,
  });

  useEffect(() => {
    if (authGate.phase !== "app") {
      clearWorkspaceLateralRouteMemory();
    }
  }, [authGate.phase]);

  useEffect(() => {
    if (isMessagesReady) {
      return;
    }

    if (authGate.phase === "loading" || authGate.phase === "error") {
      return;
    }

    const routeRequest =
      pathname === "/pdf-export"
        ? loadPdfExportRenderer
        : authGate.phase === "setup"
          ? loadSetupPage
        : authGate.phase === "login"
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
  }, [authGate.phase, isMessagesReady, pathname]);

  useEffect(() => {
    if (authGate.phase !== "app" || !canPersistLocale) {
      return;
    }

    saveLocalePreferenceApi(locale);
  }, [authGate.phase, canPersistLocale, locale]);

  const renderLoginPage = () => (
    <AppRouteSuspense>
      <LoginPage t={messages} onSubmitCredentials={login} />
    </AppRouteSuspense>
  );
  const renderSetupPage = () => (
    <AppRouteSuspense>
      <SetupPage t={messages} onSubmitCredentials={setup} />
    </AppRouteSuspense>
  );

  const renderResumeGalleryWorkspace = () => (
    <AppRouteSuspense>
      <ResumeGalleryWorkspacePage
        locale={locale}
        messages={messages}
        onLocaleChange={changeLocale}
        onLogout={logout}
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
        onLogout={logout}
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
        onLogout={logout}
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
        onLogout={logout}
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
        onLogout={logout}
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
        onLogout={logout}
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
        onLogout={logout}
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

  if (authGate.phase === "loading") {
    return <AppRouteFallback />;
  }

  if (authGate.phase === "error") {
    return (
      <AppRouteSuspense>
        <AuthStatusErrorPage
          t={messages}
          onRetry={retry}
        />
      </AppRouteSuspense>
    );
  }

  if (authGate.phase === "setup") {
    return (
      <>
        <DocumentMetadata locale={locale} messages={messages} />
        <Routes>
          <Route path="/setup" element={renderSetupPage()} />
          <Route path="*" element={<Navigate to="/setup" replace />} />
        </Routes>
      </>
    );
  }

  if (authGate.phase === "login") {
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
        <Route path="/setup" element={<Navigate to="/resume" replace />} />
        <Route path="*" element={<Navigate to="/resume" replace />} />
      </Routes>
    </>
  );
}

export default App;
