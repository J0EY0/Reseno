import {
  Suspense,
  lazy,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { loadAuthSession } from "@/lib/auth";
import {
  getWorkspaceRoute,
  workspaceRoutePaths,
  type WorkspaceRouteKind,
} from "@/lib/workspace-route";
import { getSystemLocale, type AppMessages, type Locale } from "@/i18n";
import { useLocaleMessages } from "@/i18n/use-locale-messages";
import {
  loadLocalePreferenceApi,
  saveLocalePreferenceApi,
} from "@/lib/preference-api";
import { useAuthGate } from "@/hooks/use-auth-gate";
import { Spinner } from "@/components/ui/spinner";
import { useOAuthLogin } from "@/hooks/use-oauth-login";
import {
  getWorkspaceRouteLoader,
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

const loadOAuthCallbackPage = createRouteLoader(
  () => import("@/components/auth/oauth-callback-page"),
  "OAuthCallbackPage",
);
const OAuthCallbackPage = lazy(loadOAuthCallbackPage);

const loadAuthSessionDialog = createRouteLoader(
  () => import("@/components/auth/auth-session-dialog"),
  "AuthSessionDialog",
);
const AuthSessionDialog = lazy(loadAuthSessionDialog);

const workspaceTitleKeys = {
  "resume-gallery": "myResume",
  "resume-detail": "myResume",
  "template-gallery": "resumeTemplates",
  "template-detail": "resumeTemplates",
  trash: "recycleBin",
  models: "modelSettings",
  settings: "settings",
  unknown: null,
} as const satisfies Record<WorkspaceRouteKind, keyof AppMessages | null>;

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
  const { prepareWorkspaceEntry } =
    await import("@/components/workspace/workspace-route-preparation");
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

function OAuthCallbackRoute() {
  const [initialLocale] = useState(
    () => loadLocalePreferenceApi() ?? getSystemLocale(),
  );
  const { isMessagesReady, locale, messages } =
    useLocaleMessages(initialLocale);
  if (!isMessagesReady) return null;

  return (
    <>
      <DocumentMetadata locale={locale} messages={messages} />
      <AppRouteSuspense>
        <OAuthCallbackPage t={messages} />
      </AppRouteSuspense>
    </>
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

    const titleKey = workspaceTitleKeys[getWorkspaceRoute(pathname).kind];
    const pageLabel = titleKey ? messages[titleKey] : null;

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
  return pathname === "/auth/callback" ? (
    <OAuthCallbackRoute />
  ) : (
    <WorkspaceApp />
  );
}

function WorkspaceApp() {
  const { pathname } = useLocation();
  const [initialLocale] = useState(
    () => (loadAuthSession() && loadLocalePreferenceApi()) || getSystemLocale(),
  );
  const hasEnteredAuthenticatedAppRef = useRef(false);
  const { canPersistLocale, changeLocale, isMessagesReady, locale, messages } =
    useLocaleMessages(initialLocale);
  const {
    acceptSession,
    authGate,
    destinationCommit,
    login,
    logout,
    retry,
    setup,
  } = useAuthGate({
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

  const oauthLogin = useOAuthLogin({
    enabled: isMessagesReady && authGate.phase === "login",
    onComplete: (signal) => acceptSession("resume", signal),
    t: messages,
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
      ({ clearWorkspaceRouteMemory }) => clearWorkspaceRouteMemory(),
    );
  }, [authGate.phase]);

  useEffect(() => {
    if (authGate.phase === "login" && oauthLogin.isCompleting) {
      return;
    }

    if (isMessagesReady && authGate.phase !== "app") {
      return;
    }

    if (
      authGate.phase === "loading" ||
      authGate.phase === "error" ||
      authGate.phase === "unsupported"
    ) {
      return;
    }

    const routeRequest =
      pathname === "/pdf-export"
        ? loadPdfExportRenderer
        : authGate.phase === "setup"
          ? loadSetupPage
          : authGate.phase === "login"
            ? loadLoginPage
            : getWorkspaceRouteLoader(pathname);

    const preferencesRequest =
      authGate.phase === "app" && pathname !== "/pdf-export"
        ? loadWorkspacePreferencesProvider()
        : undefined;

    // Load the destination alongside its shared layout and language catalog.
    void Promise.all([routeRequest(), preferencesRequest]).catch(
      (error: unknown) => {
        console.error(
          "Failed to preload the current application route.",
          error,
        );
      },
    );
  }, [authGate.phase, isMessagesReady, oauthLogin.isCompleting, pathname]);

  useEffect(() => {
    if (authGate.phase !== "app" || !canPersistLocale) {
      return;
    }

    saveLocalePreferenceApi(locale);
  }, [authGate.phase, canPersistLocale, locale]);

  const renderPdfExport = () => (
    <AppRouteSuspense>
      <PdfExportRenderer />
    </AppRouteSuspense>
  );

  if (!isMessagesReady || authGate.phase === "loading") {
    return appRouteFallback;
  }

  if (authGate.phase === "unsupported") {
    return (
      <AppRouteSuspense>
        <AuthStatusErrorPage
          t={messages}
          title={messages.authBrowserRequirementTitle}
          description={messages.apiMessages[authGate.reason]}
        />
      </AppRouteSuspense>
    );
  }

  if (authGate.phase === "error") {
    return (
      <AppRouteSuspense>
        <AuthStatusErrorPage t={messages} onRetry={retry} />
      </AppRouteSuspense>
    );
  }

  if (authGate.phase === "login" && oauthLogin.isCompleting) {
    return appRouteFallback;
  }

  if (authGate.phase === "setup" || authGate.phase === "login") {
    return (
      <AuthEntryRoutes
        phase={authGate.phase}
        locale={locale}
        messages={messages}
        loginPage={
          <AppRouteSuspense>
            <LoginPage
              t={messages}
              onSubmitCredentials={login}
              oauth={oauthLogin.controls}
            />
          </AppRouteSuspense>
        }
        setupPage={
          <AppRouteSuspense>
            <SetupPage t={messages} onSubmitCredentials={setup} />
          </AppRouteSuspense>
        }
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
          <Route
            element={
              <AppRouteSuspense>
                <WorkspaceLateralLayout onLogout={logout} />
              </AppRouteSuspense>
            }
          >
            <Route
              path={workspaceRoutePaths.resumeGallery}
              element={
                <AppRouteSuspense>
                  <ResumeGalleryWorkspacePage
                    onReady={
                      destinationCommit?.destination === "resume"
                        ? destinationCommit.complete
                        : undefined
                    }
                  />
                </AppRouteSuspense>
              }
            />
            <Route
              path={workspaceRoutePaths.models}
              element={
                <AppRouteSuspense>
                  <ModelsWorkspacePage />
                </AppRouteSuspense>
              }
            />
            <Route
              path={workspaceRoutePaths.settings}
              element={
                <AppRouteSuspense>
                  <SettingsWorkspacePage
                    onLogout={logout}
                    onReady={
                      destinationCommit?.destination === "settings"
                        ? destinationCommit.complete
                        : undefined
                    }
                  />
                </AppRouteSuspense>
              }
            />
            <Route
              path={workspaceRoutePaths.templateGallery}
              element={
                <AppRouteSuspense>
                  <TemplateGalleryWorkspacePage />
                </AppRouteSuspense>
              }
            />
            <Route
              path={workspaceRoutePaths.trash}
              element={
                <AppRouteSuspense>
                  <TrashWorkspacePage />
                </AppRouteSuspense>
              }
            />
          </Route>
          <Route
            path={workspaceRoutePaths.resumeDetail}
            element={
              <AppRouteSuspense>
                <ResumeDetailWorkspacePage onLogout={logout} />
              </AppRouteSuspense>
            }
          />
          <Route
            path={workspaceRoutePaths.templateDetail}
            element={
              <AppRouteSuspense>
                <TemplateDetailWorkspacePage onLogout={logout} />
              </AppRouteSuspense>
            }
          />
        </Route>
        <Route path="/login" element={<Navigate to="/resume" replace />} />
        <Route path="/setup" element={<Navigate to="/resume" replace />} />
        <Route path="*" element={<Navigate to="/resume" replace />} />
      </Routes>
      {authGate.sessionExpired ? (
        <Suspense fallback={null}>
          <AuthSessionDialog t={messages} onSubmitCredentials={login} />
        </Suspense>
      ) : null}
    </>
  );
}

export default App;
