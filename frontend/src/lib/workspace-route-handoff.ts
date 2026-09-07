const payloads = new Map<string, unknown>();
const session = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
let sequence = 0;

export function createWorkspaceHandoffToken(payload: unknown) {
  const token = `${session}-${++sequence}`;
  payloads.set(token, payload);
  return token;
}

export function readWorkspaceHandoffToken(token: unknown) {
  return typeof token === "string" ? payloads.get(token) : undefined;
}

export function deleteWorkspaceHandoffToken(token: string | null) {
  if (token) {
    payloads.delete(token);
  }
}

export function releaseWorkspaceRouteHandoff(state: unknown) {
  if (
    state &&
    typeof state === "object" &&
    "token" in state &&
    typeof state.token === "string"
  ) {
    deleteWorkspaceHandoffToken(state.token);
  }
}

export function clearWorkspaceRouteHandoffs() {
  payloads.clear();
}
