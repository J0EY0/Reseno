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
import { useAuthGate } from "@/hooks/use-auth-gate";
import { Spinner } from "@/components/ui/spinner";
import { WorkspaceEntrySkeleton } from "@/components/workspace/workspace-entry-skeleton";
import {
  loadModelsWorkspacePage,
  loadResumeDetailWorkspacePage,
  loadResumeGalleryWorkspacePage,
  loadSettingsWorkspacePage,
  loadTemplateDetailWorkspacePage,
  loadTemplateGalleryWorkspacePage,
  loadTrashWorkspacePage,
  loadWorkspaceLateralLayout,
  loadWorkspacePreferencesProvider,
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
const loadOAuthCallbackPage = createRouteLoader(
  () => import("@/components/auth/oauth-callback-page"),
  "OAuthCallbackPage",
);
const loadPdfExportRenderer = createRouteLoader(
  () => import("@/components/pdf-export-renderer"),
  "PdfExportRenderer",
);
const AuthStatusErrorPage = lazy(loadAuthStatusErrorPage);
const LoginPage = lazy(loadLoginPage);
const SetupPage = lazy(loadSetupPage);
const OAuthCallbackPage = lazy(loadOAuthCallbackPage);
const ResumeGalleryWorkspacePage = lazy(loadResumeGalleryWorkspacePage);
const WorkspaceLateralLayout = lazy(loadWorkspaceLateralLayout);
const WorkspacePreferencesProvider = lazy(loadWorkspacePreferencesProvider);
const ResumeDetailWorkspacePage = lazy(loadResumeDetailWorkspacePage);
const ModelsWorkspacePage = lazy(loadModelsWorkspacePage);
const SettingsWorkspacePage = lazy(loadSettingsWorkspacePage);
const TemplateGalleryWorkspacePage = lazy(loadTemplateGalleryWorkspacePage);
const TemplateDetailWorkspacePage = lazy(loadTemplateDetailWorkspacePage);
const TrashWorkspacePage = lazy(loadTrashWorkspacePage);
const PdfExportRenderer = lazy(loadPdfExportRenderer);

async function prepareAuthDestination(
  destination: "resume" | "settings",
  options: { signal: AbortSignal },
) {
  const { prepareWorkspaceEntry } = await import(
    "@/components/workspace/workspace-route-preparation"
  );
  options.signal.throwIfAborted();
  return prepareWorkspaceEntry(destination, options);
}

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

function AppRouteSuspense({
  children,
  fallback = appRouteFallback,
}: {
  children: ReactNode;
  fallback?: ReactNode;
}) {
  return (
    <Suspense fallback={fallback}>
      {children}
      <DynamicImportRecoveryReset />
    </Suspense>
  );
}

function OAuthCallbackRoute({
  isLoading,
  locale,
  messages,
  onComplete,
}: {
  isLoading: boolean;
  locale: Locale;
  messages: AppMessages;
  onComplete: (
    destination: "resume" | "settings",
    signal: AbortSignal,
  ) => Promise<void>;
}) {
  const { hash } = useLocation();
  const intent = new URLSearchParams(hash.slice(1)).get("intent");
  const pending = (
    <WorkspaceEntrySkeleton
      destination={intent === "bind" ? "settings" : "resume"}
      label={messages.workspaceLoading}
    />
  );

  if (isLoading) {
    return pending;
  }

  return (
    <AppRouteSuspense fallback={pending}>
      <DocumentMetadata locale={locale} messages={messages} />
      <OAuthCallbackPage
        t={messages}
        onComplete={onComplete}
      />
    </AppRouteSuspense>
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

function AuthEntryRoutes({
  phase,
  locale,
  messages,
  loginPage,
  setupPage,
  pdfPage,
}: {
  phase: "setup" | "login";
  locale: Locale;
  messages: AppMessages;
  loginPage: ReactNode;
  setupPage: ReactNode;
  pdfPage: ReactNode;
}) {
  useEffect(() => {
    if (phase !== "login") {
      return;
    }

    void loadOAuthCallbackPage().catch((error: unknown) => {
      console.error("Failed to preload the OAuth callback route.", error);
    });
  }, [phase]);

  return (
    <>
      <DocumentMetadata locale={locale} messages={messages} />
      <Routes>
        {phase === "setup" ? (
          <Route path="/setup" element={setupPage} />
        ) : (
          <>
            <Route path="/pdf-export" element={pdfPage} />
            <Route path="/login" element={loginPage} />
          </>
        )}
        <Route path="*" element={<Navigate to={`/${phase}`} replace />} />
      </Routes>
    </>
  );
}

function App() {
  const { pathname } = useLocation();
  const [initialLocale] = useState(() =>
    (loadAuthSession() && loadLocalePreferenceApi()) || getSystemLocale(),
  );
  const hasEnteredAuthenticatedAppRef = useRef(false);
  const { canPersistLocale, changeLocale, isMessagesReady, locale, messages } =
    useLocaleMessages(initialLocale);
  const { acceptSession, authGate, login, logout, retry, setup } = useAuthGate({
    loginFallbackError: messages.loginInvalidCredentials,
    onAuthenticated: () => {
      return changeLocale(loadLocalePreferenceApi() ?? getSystemLocale());
    },
    onLoggedOut: () => {
      changeLocale(getSystemLocale());
    },
    prepareDestination: prepareAuthDestination,
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
    if (isMessagesReady && authGate.phase !== "app") {
      return;
    }

    if (authGate.phase === "loading" || authGate.phase === "error") {
      return;
    }

    const routeRequest =
      pathname === "/auth/callback"
        ? loadOAuthCallbackPage
        : pathname === "/pdf-export"
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

    const preferencesRequest =
      authGate.phase === "app" &&
      pathname !== "/auth/callback" && pathname !== "/pdf-export"
        ? loadWorkspacePreferencesProvider()
        : undefined;

    // Load the destination alongside its shared layout and language catalog.
    void Promise.all([routeRequest(), preferencesRequest]).catch((error: unknown) => {
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
      <ResumeGalleryWorkspacePage />
    </AppRouteSuspense>
  );
  const renderWorkspaceLateralLayout = () => (
    <AppRouteSuspense>
      <WorkspaceLateralLayout onLogout={logout} />
    </AppRouteSuspense>
  );
  const renderResumeDetailWorkspace = () => (
    <AppRouteSuspense>
      <ResumeDetailWorkspacePage onLogout={logout} />
    </AppRouteSuspense>
  );
  const renderModelsWorkspace = () => (
    <AppRouteSuspense>
      <ModelsWorkspacePage />
    </AppRouteSuspense>
  );
  const renderSettingsWorkspace = () => (
    <AppRouteSuspense>
      <SettingsWorkspacePage onLogout={logout} />
    </AppRouteSuspense>
  );
  const renderTemplateGalleryWorkspace = () => (
    <AppRouteSuspense>
      <TemplateGalleryWorkspacePage />
    </AppRouteSuspense>
  );
  const renderTemplateDetailWorkspace = () => (
    <AppRouteSuspense>
      <TemplateDetailWorkspacePage onLogout={logout} />
    </AppRouteSuspense>
  );
  const renderTrashWorkspace = () => (
    <AppRouteSuspense>
      <TrashWorkspacePage />
    </AppRouteSuspense>
  );
  const renderPdfExport = () => (
    <AppRouteSuspense>
      <PdfExportRenderer />
    </AppRouteSuspense>
  );

  if (pathname === "/auth/callback") {
    return (
      <OAuthCallbackRoute
        isLoading={!isMessagesReady || authGate.phase === "loading"}
        locale={locale}
        messages={messages}
        onComplete={acceptSession}
      />
    );
  }

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

  if (authGate.phase === "setup" || authGate.phase === "login") {
    return (
      <AuthEntryRoutes
        phase={authGate.phase}
        locale={locale}
        messages={messages}
        loginPage={renderLoginPage()}
        setupPage={renderSetupPage()}
        pdfPage={renderPdfExport()}
      />
    );
  }

  return (
    <>
      <DocumentMetadata locale={locale} messages={messages} />
      <Routes>
        <Route path="/pdf-export" element={renderPdfExport()} />
        <Route
          element={
            <AppRouteSuspense>
              <WorkspacePreferencesProvider
                locale={locale}
                messages={messages}
                onLocaleChange={changeLocale}
              />
            </AppRouteSuspense>
          }
        >
          <Route element={renderWorkspaceLateralLayout()}>
            <Route path="/resume" element={renderResumeGalleryWorkspace()} />
            <Route path="/models" element={renderModelsWorkspace()} />
            <Route path="/settings" element={renderSettingsWorkspace()} />
            <Route path="/templates" element={renderTemplateGalleryWorkspace()} />
            <Route path="/trash" element={renderTrashWorkspace()} />
          </Route>
          <Route path="/resume/:id" element={renderResumeDetailWorkspace()} />
          <Route path="/template/:id" element={renderTemplateDetailWorkspace()} />
        </Route>
        <Route path="/login" element={<Navigate to="/resume" replace />} />
        <Route path="/setup" element={<Navigate to="/resume" replace />} />
        <Route path="*" element={<Navigate to="/resume" replace />} />
      </Routes>
    </>
  );
}

export default App;
