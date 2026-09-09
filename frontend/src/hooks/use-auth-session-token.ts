import { useSyncExternalStore } from "react";

import {
  AUTH_SESSION_KEY,
  AUTH_SESSION_UPDATED_EVENT,
  getAccessToken,
} from "@/lib/auth-session";
import {
  AUTH_SESSION_INVALIDATED_EVENT,
  AUTH_SESSION_RESTORED_EVENT,
} from "@/lib/api-auth";

function subscribe(listener: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (
      event.storageArea === window.localStorage &&
      (event.key === AUTH_SESSION_KEY || event.key === null)
    ) {
      listener();
    }
  };
  window.addEventListener(AUTH_SESSION_UPDATED_EVENT, listener);
  window.addEventListener(AUTH_SESSION_INVALIDATED_EVENT, listener);
  window.addEventListener(AUTH_SESSION_RESTORED_EVENT, listener);
  window.addEventListener("focus", listener);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(AUTH_SESSION_UPDATED_EVENT, listener);
    window.removeEventListener(AUTH_SESSION_INVALIDATED_EVENT, listener);
    window.removeEventListener(AUTH_SESSION_RESTORED_EVENT, listener);
    window.removeEventListener("focus", listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useAuthSessionToken() {
  return useSyncExternalStore(subscribe, getAccessToken, () => null);
}
