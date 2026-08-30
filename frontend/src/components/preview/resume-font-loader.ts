import { useEffect, useState } from "react";

import type { AppMessages } from "@/i18n";
import type { ResumeData, ResumeFontFamily } from "@/types/resume";

interface ReadyFontSnapshot {
  fontFamily: ResumeFontFamily;
  messages: AppMessages;
  resume: ResumeData;
  token: object;
}

let notoSansStylesPromise: Promise<unknown> | null = null;
let notoSerifStylesPromise: Promise<unknown> | null = null;

function loadNotoSansStyles() {
  // Keep literal import paths so Vite emits one predictable optional CSS entry.
  notoSansStylesPromise ??= import(
    "@fontsource-variable/noto-sans-sc/wght.css"
  ).catch((error) => {
    notoSansStylesPromise = null;
    throw error;
  });

  return notoSansStylesPromise;
}

function loadNotoSerifStyles() {
  notoSerifStylesPromise ??= import(
    "@fontsource-variable/noto-serif-sc/wght.css"
  ).catch((error) => {
    notoSerifStylesPromise = null;
    throw error;
  });

  return notoSerifStylesPromise;
}

const resumeFontStyleLoaders: Record<
  ResumeFontFamily,
  () => Promise<unknown>
> = {
  inter: loadNotoSansStyles,
  noto_sans_sc: loadNotoSansStyles,
  plex: loadNotoSansStyles,
  serif: loadNotoSerifStyles,
};

export function loadResumeFontStyles(fontFamily: ResumeFontFamily) {
  return resumeFontStyleLoaders[fontFamily]();
}

function waitForAnimationFrame() {
  return new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

async function waitWithTimeout(promise: Promise<unknown>, timeoutMs: number) {
  let timeoutId: number | undefined;

  try {
    await Promise.race([
      promise,
      new Promise<void>((resolve) => {
        timeoutId = window.setTimeout(resolve, timeoutMs);
      }),
    ]);
  } finally {
    if (timeoutId !== undefined) {
      window.clearTimeout(timeoutId);
    }
  }
}

async function prepareResumeFont(fontFamily: ResumeFontFamily) {
  try {
    // Do not declare pagination ready while a stylesheet can still arrive late.
    await loadResumeFontStyles(fontFamily);
  } catch {
    // A failed stylesheet leaves the existing system-font fallback stable.
  }

  // Let the settled stylesheet reach the rendered document before reading FontFaceSet.
  await waitForAnimationFrame();
  await waitWithTimeout(
    document.fonts?.ready ?? Promise.resolve(),
    2_500,
  );
}

export function useResumeFontReadyToken(
  fontFamily: ResumeFontFamily,
  resume: ResumeData,
  messages: AppMessages,
): object | null {
  const [readySnapshot, setReadySnapshot] =
    useState<ReadyFontSnapshot | null>(null);
  const isReady = Boolean(
    readySnapshot?.fontFamily === fontFamily &&
      readySnapshot.resume === resume &&
      readySnapshot.messages === messages,
  );

  useEffect(() => {
    let cancelled = false;

    void prepareResumeFont(fontFamily).then(() => {
      if (!cancelled) {
        setReadySnapshot({ fontFamily, messages, resume, token: {} });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [fontFamily, messages, resume]);

  return isReady ? readySnapshot?.token ?? null : null;
}
