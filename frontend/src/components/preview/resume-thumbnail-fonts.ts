import { useEffect } from "react";

import { loadResumeFontStyles } from "@/components/preview/resume-font-loader";
import type { ResumeFontFamily } from "@/types/resume";

export function useResumeThumbnailFonts(
  fontFamilies: readonly ResumeFontFamily[],
) {
  const needsSansStyles = fontFamilies.some(
    (fontFamily) => fontFamily !== "serif",
  );
  const needsSerifStyles = fontFamilies.includes("serif");

  useEffect(() => {
    if (needsSansStyles) {
      void loadResumeFontStyles("inter").catch(() => undefined);
    }
    if (needsSerifStyles) {
      void loadResumeFontStyles("serif").catch(() => undefined);
    }
  }, [needsSansStyles, needsSerifStyles]);
}
