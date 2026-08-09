import type { Locale } from "@/i18n";
import type { AgentSettings, ThemeMode } from "@/types/resume";

export interface WorkspacePreferencesSnapshot {
  locale: Locale;
  theme: ThemeMode;
  agentSettings: AgentSettings;
}

interface WorkspacePreferencesSaveHandlers {
  onError: (error: unknown) => void;
  onRollback: (snapshot: WorkspacePreferencesSnapshot) => void;
}

export interface WorkspacePreferencesPersistence {
  flush: () => Promise<void>;
  getSnapshot: () => WorkspacePreferencesSnapshot | null;
  hydrate: (snapshot: WorkspacePreferencesSnapshot) => void;
  enqueue: (
    snapshot: WorkspacePreferencesSnapshot,
    save: () => Promise<unknown>,
    handlers: WorkspacePreferencesSaveHandlers,
  ) => void;
}

/**
 * Owns the one cross-route invariant for preference writes: full snapshots are
 * committed in order, and only the latest failed mutation may roll UI state
 * back. Page data and rendering remain owned by their route components.
 */
export function createWorkspacePreferencesPersistence(): WorkspacePreferencesPersistence {
  let queue = Promise.resolve();
  let latestMutationId = 0;
  let persistedSnapshot: WorkspacePreferencesSnapshot | null = null;

  return {
    flush: () => queue,
    getSnapshot: () => persistedSnapshot,
    hydrate(snapshot) {
      persistedSnapshot = snapshot;
    },
    enqueue(snapshot, save, handlers) {
      const mutationId = ++latestMutationId;
      const request = queue.then(async () => {
        await save();
        persistedSnapshot = snapshot;
      });

      // The shared queue includes rollback handling, so a new route that calls
      // flush() cannot hydrate until the failed snapshot is fully reconciled.
      queue = request.catch((error: unknown) => {
        if (mutationId === latestMutationId && persistedSnapshot) {
          handlers.onRollback(persistedSnapshot);
        }
        handlers.onError(error);
      });
    },
  };
}
