import type { Locale } from "@/i18n";
import {
  loadLocalePreference,
  saveLocalePreference,
} from "@/lib/workspace-storage";

export function loadLocalePreferenceApi() {
  return loadLocalePreference();
}

export function saveLocalePreferenceApi(locale: Locale) {
  saveLocalePreference(locale);
}
