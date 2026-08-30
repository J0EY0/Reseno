import { useEffect } from "react";
import { useRouteError } from "react-router-dom";

import {
  getApplicationRouteErrorDetails,
  tryReloadAfterDynamicImportFailure,
} from "@/lib/dynamic-import-recovery";

export function AppRouteErrorPage() {
  const error = useRouteError();
  const details = getApplicationRouteErrorDetails(error);
  const isDynamicImportError = details.kind === "dynamic-import";

  useEffect(() => {
    console.error("Application route rendering failed.", error);
    if (isDynamicImportError) {
      tryReloadAfterDynamicImportFailure(error);
    }
  }, [error, isDynamicImportError]);

  return (
    <main className="flex min-h-svh items-center justify-center bg-background p-6">
      <section
        role="alert"
        className="w-full max-w-md rounded-(--radius-card) border border-border bg-card p-8 text-center shadow-card"
      >
        <h1 className="text-xl font-semibold text-foreground">
          {isDynamicImportError ? "页面资源加载失败" : "页面运行出错"}
        </h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {isDynamicImportError
            ? "页面模块仍未能从服务器加载，请确认服务正常后再重试。"
            : "页面执行过程中发生错误，请返回简历页或重新加载后重试。"}
        </p>
        {details.message ? (
          <p className="mt-4 break-words rounded-lg bg-muted px-3 py-2 text-left font-mono text-xs leading-5 text-muted-foreground">
            {details.message}
          </p>
        ) : null}
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          {window.location.pathname !== "/resume" ? (
            <button
              type="button"
              className="inline-flex h-10 items-center justify-center rounded-md border border-border bg-background px-5 text-sm font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              onClick={() => window.location.assign("/resume")}
            >
              返回我的简历
            </button>
          ) : null}
          <button
            type="button"
            className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            onClick={() => window.location.reload()}
          >
            重新加载
          </button>
        </div>
      </section>
    </main>
  );
}
