export function getResumeDraftReviewPaths(element: HTMLElement) {
  return (element.dataset.resumeDiffPath ?? "").split(" ").filter(Boolean);
}

export function isVisibleResumeDraftReviewTarget(element: HTMLElement) {
  if (element.closest("[inert]")) {
    return false;
  }

  const clippingElement = element.closest<HTMLElement>(
    ".resume-page-content-viewport, .resume-page-flow-viewport",
  );
  if (!clippingElement) {
    return true;
  }

  const targetRect = element.getBoundingClientRect();
  const clippingRect = clippingElement.getBoundingClientRect();
  return (
    targetRect.bottom > clippingRect.top + 1 &&
    targetRect.top < clippingRect.bottom - 1
  );
}

export function getResumeDraftReviewTargetElement(
  eventTarget: EventTarget | null,
  root: HTMLElement | null,
) {
  if (!(eventTarget instanceof Element) || !root) {
    return null;
  }
  const element = eventTarget.closest<HTMLElement>("[data-resume-diff-path]");
  return element && root.contains(element) && !element.closest("[inert]")
    ? element
    : null;
}
