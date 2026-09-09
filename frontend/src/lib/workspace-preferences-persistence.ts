import type { Locale } from "@/i18n";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import { saveWorkspaceThemePreference } from "@/lib/workspace-theme";
import type { AgentSettings, ModelConfig, ThemeMode } from "@/types/resume";

export interface WorkspacePreferencesSnapshot {
  locale: Locale;
  theme: ThemeMode;
  agentSettings: AgentSettings | null;
}

type WorkspacePreferencesPatch = Partial<{
  locale: Locale;
  theme: ThemeMode;
  agentSettings: AgentSettings;
}>;

interface WorkspacePreferencesData {
  theme?: ThemeMode;
  agentSettings?: AgentSettings;
  modelConfigs?: ModelConfig[];
}

interface WorkspacePreferencesHandlers {
  onChange: (snapshot: WorkspacePreferencesSnapshot) => void;
  onError: (error: unknown, locale: Locale) => void;
  save: (
    patch: WorkspacePreferencesPatch,
    locale: Locale,
  ) => Promise<WorkspacePreferencesPatch>;
}

export interface WorkspacePreferencesPersistence {
  change: (patch: WorkspacePreferencesPatch) => void;
  flush: () => Promise<void>;
  getSnapshot: () => WorkspacePreferencesSnapshot;
  prepareRead: (
    signal: AbortSignal,
  ) => Promise<(data: WorkspacePreferencesData) => void>;
  reconcileModels: (configs: ModelConfig[]) => void;
  reset: (snapshot: WorkspacePreferencesSnapshot) => void;
  synchronizeLocale: (locale: Locale) => void;
}

const fields = ["locale", "theme", "agentSettings"] as const;
type PreferenceField = (typeof fields)[number];

function equalSettings(
  left: AgentSettings | null,
  right: AgentSettings | null,
) {
  return (
    left === right ||
    (left !== null &&
      right !== null &&
      left.defaultModelConfigId === right.defaultModelConfigId &&
      left.responseLanguage === right.responseLanguage &&
      left.behaviorMode === right.behaviorMode &&
      left.confirmationMode === right.confirmationMode)
  );
}

export function createWorkspacePreferencesPersistence(
  initial: WorkspacePreferencesSnapshot,
  handlers: WorkspacePreferencesHandlers,
): WorkspacePreferencesPersistence {
  let confirmed = initial;
  let current = initial;
  let generation = 0;
  let localeSyncRevision = 0;
  let queue = Promise.resolve();
  let pending: { patch: WorkspacePreferencesPatch }[] = [];
  let modelIds: string[] | null = null;
  let nextReadId = 0;
  const revisions: Record<PreferenceField, number> = {
    locale: 0,
    theme: 0,
    agentSettings: 0,
  };
  const acceptedReads = { theme: 0, agentSettings: 0 };

  function normalize(settings: AgentSettings | null) {
    return settings && modelIds !== null
      ? normalizeAgentSettings(
          settings,
          modelIds.map((id) => ({ id })),
        )
      : settings;
  }

  function publish() {
    const next = pending.reduce(
      (snapshot, mutation) => ({ ...snapshot, ...mutation.patch }),
      confirmed,
    );
    next.agentSettings = normalize(next.agentSettings);
    if (
      current.locale === next.locale &&
      current.theme === next.theme &&
      equalSettings(current.agentSettings, next.agentSettings)
    ) {
      return;
    }
    current = next;
    handlers.onChange(current);
  }

  function commit(patch: WorkspacePreferencesPatch) {
    confirmed = { ...confirmed, ...patch };
    confirmed.agentSettings = normalize(confirmed.agentSettings);
    if (patch.theme !== undefined) {
      saveWorkspaceThemePreference(confirmed.theme);
    }
  }

  function change(patch: WorkspacePreferencesPatch) {
    if (patch.agentSettings) {
      patch = { ...patch, agentSettings: normalize(patch.agentSettings)! };
    }
    const changedFields = fields.filter(
      (field) =>
        patch[field] !== undefined &&
        (field === "agentSettings"
          ? !equalSettings(current.agentSettings, patch.agentSettings!)
          : current[field] !== patch[field]),
    );
    if (changedFields.length === 0) {
      return;
    }
    for (const field of changedFields) {
      revisions[field] += 1;
    }
    const mutation = { patch };
    const owner = generation;
    pending.push(mutation);
    publish();
    queue = queue.then(async () => {
      if (owner !== generation) {
        return;
      }
      try {
        const submittedLocaleRevision = localeSyncRevision;
        const response = await handlers.save(
          mutation.patch,
          mutation.patch.locale ?? confirmed.locale,
        );
        if (owner !== generation) {
          return;
        }
        commit(
          submittedLocaleRevision === localeSyncRevision
            ? response
            : { ...response, locale: confirmed.locale },
        );
      } catch (error) {
        if (owner !== generation) {
          return;
        }
        handlers.onError(error, current.locale);
      } finally {
        if (owner === generation) {
          pending = pending.filter((item) => item !== mutation);
          publish();
        }
      }
    });
  }

  async function flush() {
    let waiting;
    do {
      waiting = queue;
      await waiting;
    } while (waiting !== queue);
  }

  return {
    change,
    flush,
    getSnapshot: () => current,
    async prepareRead(signal) {
      const owner = generation;
      await flush();
      const readId = ++nextReadId;
      const before = { ...revisions };
      const pendingFields = new Set(
        pending.flatMap(({ patch }) => Object.keys(patch)),
      );
      return (data) => {
        if (signal.aborted || owner !== generation) {
          return;
        }
        const patch: WorkspacePreferencesPatch = {};
        for (const field of ["theme", "agentSettings"] as const) {
          if (
            data[field] === undefined ||
            pendingFields.has(field) ||
            revisions[field] !== before[field] ||
            readId < acceptedReads[field]
          ) {
            continue;
          }
          acceptedReads[field] = readId;
          if (field === "theme") {
            patch.theme = data.theme;
          } else {
            if (data.modelConfigs !== undefined) {
              modelIds = data.modelConfigs.map((config) => config.id);
            }
            patch.agentSettings = normalize(data.agentSettings!)!;
          }
        }
        commit(patch);
        publish();
      };
    },
    reconcileModels(configs) {
      revisions.agentSettings += 1;
      const previous = current.agentSettings;
      modelIds = configs.map((config) => config.id);
      confirmed = {
        ...confirmed,
        agentSettings: normalize(confirmed.agentSettings),
      };
      for (const mutation of pending) {
        if (mutation.patch.agentSettings) {
          mutation.patch = {
            ...mutation.patch,
            agentSettings: normalize(mutation.patch.agentSettings)!,
          };
        }
      }
      if (previous) {
        change({ agentSettings: normalize(previous)! });
      }
      publish();
    },
    synchronizeLocale(locale) {
      if (
        pending.some(({ patch }) => patch.locale !== undefined) ||
        confirmed.locale === locale
      ) {
        return;
      }
      localeSyncRevision += 1;
      confirmed = { ...confirmed, locale };
      publish();
    },
    reset(snapshot) {
      generation += 1;
      pending = [];
      modelIds = null;
      confirmed = snapshot;
      for (const field of fields) {
        revisions[field] += 1;
      }
      publish();
    },
  };
}
