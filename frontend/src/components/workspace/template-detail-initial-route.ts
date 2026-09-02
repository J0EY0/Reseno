import type { AppMessages } from "@/i18n";
import { getTemplateCatalog } from "@/lib/templates";
import { getTemplateDetailRouteHandoff } from "@/lib/workspace-route";

export function resolveInitialTemplateDetail(
  messages: AppMessages,
  routeState: unknown,
  templateId: string,
) {
  const handoff = getTemplateDetailRouteHandoff(routeState, templateId);
  if (!handoff) {
    return null;
  }

  const template = getTemplateCatalog(
    messages,
    handoff.data.customTemplates,
  ).find((item) => item.id === templateId);

  return template
    ? {
        data: handoff.data,
        template,
        templateLocale: handoff.templateLocale,
      }
    : null;
}
