import { createContext } from "react";

import type { AppMessages } from "@/i18n";

export const ResourceRecoveryContext = createContext<{
  messages: AppMessages;
  saveAndReload: (signal?: AbortSignal) => Promise<void>;
} | null>(null);
