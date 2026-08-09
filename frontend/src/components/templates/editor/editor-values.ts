export const readonlyDisabledControlClassName =
  "disabled:pointer-events-auto disabled:cursor-not-allowed";

export function getScaleLabel(baseFontSize: number, value: number) {
  return `~${Math.round(baseFontSize * value)}px`;
}
