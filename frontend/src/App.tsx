import {
  Suspense,
  lazy,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
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
import { useAuthGate } from "@/hooks/use-auth-gate";
import { Spinner } from "@/components/ui/spinner";
import {
  loadModelsWorkspacePage,
  loadResumeDetailWorkspacePage,
  loadResumeGalleryWorkspacePage,
  loadSettingsWorkspacePage,
  loadTemplateDetailWorkspacePage,
  loadTemplateGalleryWorkspacePage,
  loadTrashWorkspacePage,
  loadWorkspaceLateralLayout,
} from "@/components/workspace/workspace-route-loaders";
import { clearDynamicImportReloadGuard } from "@/lib/dynamic-import-recovery";
import { createRouteLoader } from "@/lib/route-loader";

const loadAuthStatusErrorPage = createRouteLoader(
  () => import("@/components/auth/auth-status-error-page"),
  "AuthStatusErrorPage",
);
const loadLoginPage = createRouteLoader(
  () => import("@/components/auth/login-page"),
  "LoginPage",
);
const loadSetupPage = createRouteLoader(
  () => import("@/components/auth/setup-page"),
  "SetupPage",
);
const loadPdfExportRenderer = createRouteLoader(
  () => import("@/components/pdf-export-renderer"),
  "PdfExportRenderer",
);
const AuthStatusErrorPage = lazy(loadAuthStatusErrorPage);
const LoginPage = lazy(loadLoginPage);
const SetupPage = lazy(loadSetupPage);
const ResumeGalleryWorkspacePage = lazy(loadResumeGalleryWorkspacePage);
const WorkspaceLateralLayout = lazy(loadWorkspaceLateralLayout);
const ResumeDetailWorkspacePage = lazy(loadResumeDetailWorkspacePage);
const ModelsWorkspacePage = lazy(loadModelsWorkspacePage);
const SettingsWorkspacePage = lazy(loadSettingsWorkspacePage);
const TemplateGalleryWorkspacePage = lazy(loadTemplateGalleryWorkspacePage);
const TemplateDetailWorkspacePage = lazy(loadTemplateDetailWorkspacePage);
const TrashWorkspacePage = lazy(loadTrashWorkspacePage);
const PdfExportRenderer = lazy(loadPdfExportRenderer);

const appRouteFallback = (
  <div className="grid h-svh place-items-center">
    <Spinner className="size-8" />
  </div>
);

function DynamicImportRecoveryReset() {
  const key = useLocation().key;

  useEffect(clearDynamicImportReloadGuard, [key]);

  return null;
}

function AppRouteSuspense({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={appRouteFallback}>
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
    (loadAuthSession() && loadLocalePreferenceApi()) || getSystemLocale(),
  );
  const [preferencesPersistence] = useState(() =>
    createWorkspacePreferencesPersistence(),
  );
  const hasEnteredAuthenticatedAppRef = useRef(false);
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
    if (authGate.phase === "app") {
      hasEnteredAuthenticatedAppRef.current = true;
      return;
    }
    if (!hasEnteredAuthenticatedAppRef.current) {
      return;
    }

    hasEnteredAuthenticatedAppRef.current = false;
    void import("@/lib/workspace-route-memory").then(
      ({ clearWorkspaceLateralRouteMemory }) =>
        clearWorkspaceLateralRouteMemory(),
    );
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
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderWorkspaceLateralLayout = () => (
    <AppRouteSuspense>
      <WorkspaceLateralLayout
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
        persistence={preferencesPersistence}
      />
    </AppRouteSuspense>
  );
  const renderPdfExport = () => (
    <AppRouteSuspense>
      <PdfExportRenderer />
    </AppRouteSuspense>
  );

  if (!isMessagesReady || authGate.phase === "loading") {
    return appRouteFallback;
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
        <Route element={renderWorkspaceLateralLayout()}>
          <Route path="/resume" element={renderResumeGalleryWorkspace()} />
          <Route path="/models" element={renderModelsWorkspace()} />
          <Route path="/settings" element={renderSettingsWorkspace()} />
          <Route path="/templates" element={renderTemplateGalleryWorkspace()} />
          <Route path="/trash" element={renderTrashWorkspace()} />
        </Route>
        <Route path="/resume/:id" element={renderResumeDetailWorkspace()} />
        <Route path="/template/:id" element={renderTemplateDetailWorkspace()} />
        <Route path="/login" element={<Navigate to="/resume" replace />} />
        <Route path="/setup" element={<Navigate to="/resume" replace />} />
        <Route path="*" element={<Navigate to="/resume" replace />} />
      </Routes>
    </>
  );
}

export default App;
