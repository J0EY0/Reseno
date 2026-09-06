import { useCallback, useRef, useState } from "react";

import type { Locale } from "@/i18n";
import { normalizeModelConfigs } from "@/lib/model-config";
import type { ResumeEditorRouteData } from "@/lib/workspace-route-data";
import type { ModelConfig } from "@/types/resume";

export function useResumeDetailModels({
  initialRouteData,
  locale,
}: {
  initialRouteData?: ResumeEditorRouteData;
  locale: Locale;
}) {
  const initialLocaleRef = useRef(locale);
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>(() =>
    normalizeModelConfigs(initialRouteData, locale),
  );
  const hydrateModels = useCallback((source: ResumeEditorRouteData) => {
    setModelConfigs(normalizeModelConfigs(source, initialLocaleRef.current));
  }, []);

  return { hydrateModels, modelConfigs };
}
