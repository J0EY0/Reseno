import { getMessagesSync, getSystemLocale } from "@/i18n";
import { loadLocalePreference } from "@/lib/workspace-storage";

export function resolveApiMessage(messageKey: string) {
  const locale = loadLocalePreference() ?? getSystemLocale();
  const messages = getMessagesSync(locale);
  const apiMessages = messages.apiMessages as Record<string, string>;

  return apiMessages[messageKey] ?? messages.apiMessages.REQUEST_FAILED;
}
