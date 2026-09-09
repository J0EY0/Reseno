export const SIDEBAR_COOKIE_NAME = "sidebar_state";
export const SIDEBAR_WIDTH = "16rem";
export const SIDEBAR_WIDTH_ICON = "3rem";

export function getInitialSidebarOpen(defaultOpen: boolean) {
  if (typeof document === "undefined") {
    return defaultOpen;
  }

  const cookiePrefix = `${SIDEBAR_COOKIE_NAME}=`;
  const sidebarCookie = document.cookie
    .split(";")
    .map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith(cookiePrefix));
  const cookieValue = sidebarCookie?.slice(cookiePrefix.length);

  if (cookieValue === "true") {
    return true;
  }
  if (cookieValue === "false") {
    return false;
  }
  return defaultOpen;
}
