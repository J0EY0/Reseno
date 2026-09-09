import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppRouteErrorPage } from "./components/app-route-error-page.tsx";
import { installDynamicImportRecovery } from "./lib/dynamic-import-recovery.ts";
import "@fontsource-variable/ibm-plex-sans/wght.css";
import "@fontsource-variable/inter/wght.css";
import "./assets/fonts/latin-modern/italic.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./index.css";
import App from "./App.tsx";

installDynamicImportRecovery();

const router = createBrowserRouter([
  {
    path: "*",
    element: <App />,
    errorElement: <AppRouteErrorPage />,
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
