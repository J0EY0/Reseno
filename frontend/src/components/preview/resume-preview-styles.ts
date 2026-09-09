import type { CSSProperties } from "react";

import type { ResumeFontFamily, ResumeTemplateSettings } from "@/types/resume";

const fontFamilyMap: Record<ResumeFontFamily, string> = {
  inter:
    '"Inter Variable","Inter","Noto Sans SC Variable","Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif',
  noto_sans_sc:
    '"Noto Sans SC Variable","Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif',
  serif:
    '"Noto Serif SC Variable","Noto Serif SC","Source Serif 4","Songti SC","STSong","Times New Roman",serif',
  times:
    '"Times New Roman",Times,"Liberation Serif","Noto Serif SC Variable","Noto Serif SC",serif',
  plex: '"IBM Plex Sans Variable","IBM Plex Sans","Noto Sans SC Variable","Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif',
};

export function createResumePreviewStyles({
  contentWidthMm,
  fontFamily,
  fontSize,
  isSidebarLayout,
  settings,
}: {
  contentWidthMm: number;
  fontFamily: ResumeFontFamily;
  fontSize: number;
  isSidebarLayout: boolean;
  settings: ResumeTemplateSettings;
}) {
  const fontStack = fontFamilyMap[fontFamily];
  const colorVariables: CSSProperties = {
    ["--resume-page-bg" as string]: settings.pageBackground,
    ["--resume-surface-color" as string]: settings.surfaceColor,
    ["--resume-heading-color" as string]: settings.headingColor,
    ["--resume-body-color" as string]: settings.bodyColor,
    ["--resume-muted-color" as string]: settings.mutedColor,
    ["--resume-divider-color" as string]: settings.dividerColor,
  };
  const sharedStyles: CSSProperties = {
    ...colorVariables,
    ["--resume-name-tracking" as string]:
      fontFamily === "times" ? "0" : "-0.04em",
    backgroundColor: settings.pageBackground,
    color: settings.bodyColor,
    fontFamily: fontStack,
    fontSize: `${fontSize}px`,
  };

  return {
    contentFlowStyle: {
      ...sharedStyles,
      width: `${contentWidthMm}mm`,
    } satisfies CSSProperties,
    pageStyle: {
      ...sharedStyles,
      paddingTop: isSidebarLayout ? 0 : `${settings.pagePaddingTop}mm`,
      paddingRight: isSidebarLayout ? 0 : `${settings.pagePaddingX}mm`,
      paddingBottom: isSidebarLayout ? 0 : `${settings.pagePaddingBottom}mm`,
      paddingLeft: isSidebarLayout ? 0 : `${settings.pagePaddingX}mm`,
    } satisfies CSSProperties,
  };
}
