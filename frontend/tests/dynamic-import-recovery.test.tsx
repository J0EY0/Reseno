// @vitest-environment-options {"console": true}
import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {} from "vitest/jsdom";

import { AppRouteErrorPage } from "@/components/app-route-error-page";
import en from "@/i18n/locales/en.json";
import {
  getApplicationRouteErrorDetails,
  isDynamicImportFailure,
} from "@/lib/dynamic-import-recovery";

const classifications: [
  unknown,
  "dynamic-import" | "unexpected",
  string | null,
][] = [
  [
    new Error("ordinary render failure"),
    "unexpected",
    "ordinary render failure",
  ],
  [
    new TypeError("Failed to fetch dynamically imported module: /route.js"),
    "dynamic-import",
    "Failed to fetch dynamically imported module: /route.js",
  ],
  ...[
    "Importing a module script failed",
    "Error loading dynamically imported module",
    "ChunkLoadError",
    "Loading chunk 42 failed",
    "Unable to preload CSS for /assets/x.css",
  ].map((message): [unknown, "dynamic-import", string] => [
    message,
    "dynamic-import",
    message,
  ]),
  [
    {
      data: "Workspace loader failed",
      status: 500,
      statusText: "Internal Server Error",
    },
    "unexpected",
    "Workspace loader failed",
  ],
  [{ data: { message: "ChunkLoadError" } }, "dynamic-import", "ChunkLoadError"],
  [{ statusText: "Gateway Timeout" }, "unexpected", "Gateway Timeout"],
  [
    { message: "Render failure", data: "ChunkLoadError" },
    "unexpected",
    "Render failure",
  ],
  [null, "unexpected", null],
  [undefined, "unexpected", null],
  [42, "unexpected", null],
  [{ message: 42, data: {} }, "unexpected", null],
];

it.each(classifications)(
  "classifies %j as %s and preserves its message",
  (error, kind, message) => {
    expect(getApplicationRouteErrorDetails(error)).toStrictEqual({
      kind,
      message,
    });
    expect(isDynamicImportFailure(error)).toBe(kind === "dynamic-import");
  },
);

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-US"]);
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

it.each([
  [
    "/models",
    new TypeError("Failed to fetch dynamically imported module: /route.js"),
    en.routeResourceLoadErrorTitle,
    en.routeResourceLoadErrorDescription,
  ],
  [
    "/resume",
    new Error("ordinary render failure"),
    en.routeRuntimeErrorTitle,
    en.routeRuntimeErrorDescription,
  ],
])(
  "keeps the %s error page available until the user reloads",
  async (pathname, error, title, description) => {
    window.history.replaceState(null, "", pathname);
    const navigation = vi.fn();
    jsdom.virtualConsole.on("jsdomError", navigation);
    const router = createMemoryRouter(
      [
        {
          path: "*",
          loader: () => {
            throw error;
          },
          element: <div>Loaded route</div>,
          hydrateFallbackElement: <div>Loading route</div>,
          errorElement: <AppRouteErrorPage />,
        },
      ],
      { initialEntries: [pathname] },
    );
    try {
      render(<RouterProvider router={router} />);
      expect(await screen.findByRole("heading", { name: title })).toBeTruthy();
      expect(screen.getByText(description)).toBeTruthy();
      expect(screen.getByText(error.message)).toBeTruthy();
      expect(screen.getByRole("alert").closest("main")?.lang).toBe("en");
      expect(
        Boolean(screen.queryByRole("button", { name: en.backToResumes })),
      ).toBe(pathname !== "/resume");
      expect(navigation).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: en.reloadPage }));
      expect(navigation).toHaveBeenCalledOnce();
      expect(navigation.mock.calls[0][0]).toMatchObject({
        message: expect.stringContaining("navigation"),
        type: "not-implemented",
      });
      if (pathname !== "/resume") {
        const assign = vi.fn();
        const browserLocation = window.location;
        vi.stubGlobal(
          "window",
          new Proxy(window, {
            get(target, key) {
              return key === "location"
                ? {
                    pathname: browserLocation.pathname,
                    assign,
                  }
                : Reflect.get(target, key, target);
            },
          }),
        );
        fireEvent.click(screen.getByRole("button", { name: en.backToResumes }));
        expect(assign).toHaveBeenCalledExactlyOnceWith("/resume");
        expect(navigation).toHaveBeenCalledOnce();
      }
    } finally {
      vi.unstubAllGlobals();
      router.dispose();
      jsdom.virtualConsole.off("jsdomError", navigation);
    }
  },
);
