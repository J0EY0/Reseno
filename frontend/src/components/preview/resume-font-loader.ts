import { useEffect, useState } from "react";

import type { AppMessages } from "@/i18n";
import type { ResumeData, ResumeFontFamily } from "@/types/resume";

interface ReadyFontSnapshot {
  fontFamily: ResumeFontFamily;
  messages: AppMessages;
  resume: ResumeData;
  token: object;
}

let sansStylesPromise: Promise<unknown> | null = null;
let serifStylesPromise: Promise<unknown> | null = null;

function loadSansStyles() {
  sansStylesPromise ??= import("@/assets/fonts/resume-sans.css").catch(
    (error) => {
      sansStylesPromise = null;
      throw error;
    },
  );

  return sansStylesPromise;
}

function loadSerifStyles() {
  serifStylesPromise ??= import("@/assets/fonts/resume-serif.css").catch(
    (error) => {
      serifStylesPromise = null;
      throw error;
    },
  );

  return serifStylesPromise;
}

export function loadResumeFontStyles(fontFamily: ResumeFontFamily) {
  return fontFamily === "serif" || fontFamily === "times"
    ? loadSerifStyles()
    : loadSansStyles();
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
  await waitWithTimeout(document.fonts?.ready ?? Promise.resolve(), 2_500);
}

export function useResumeFontReadyToken(
  fontFamily: ResumeFontFamily,
  resume: ResumeData,
  messages: AppMessages,
): object | null {
  const [readySnapshot, setReadySnapshot] = useState<ReadyFontSnapshot | null>(
    null,
  );
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

  return isReady ? (readySnapshot?.token ?? null) : null;
}
