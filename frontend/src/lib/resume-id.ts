const RESUME_NODE_ID_PATTERN = /^[A-Za-z0-9-]+$/;

export function createId(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

export function isResumeNodeId(value: unknown): value is string {
  return typeof value === "string" && RESUME_NODE_ID_PATTERN.test(value);
}
