import type {
  BundledLanguage,
  BundledTheme,
  HighlighterGeneric,
  ThemedToken,
} from "shiki";

export interface TokenizedCode {
  tokens: ThemedToken[][];
  fg: string;
  bg: string;
}

const highlighterCache = new Map<
  string,
  Promise<HighlighterGeneric<BundledLanguage, BundledTheme>>
>();
const tokensCache = new Map<string, TokenizedCode>();
const subscribers = new Map<
  string,
  Set<(result: TokenizedCode) => void>
>();

export function getTokensCacheKey(
  code: string,
  language: BundledLanguage,
) {
  const start = code.slice(0, 100);
  const end = code.length > 100 ? code.slice(-100) : "";

  return `${language}:${code.length}:${start}:${end}`;
}

function getHighlighter(
  language: BundledLanguage,
): Promise<HighlighterGeneric<BundledLanguage, BundledTheme>> {
  const cached = highlighterCache.get(language);
  if (cached) {
    return cached;
  }

  const highlighterPromise = Promise.all([
    import("shiki/core"),
    import("shiki/engine/javascript"),
    import("shiki/langs/json.mjs"),
    import("shiki/themes/github-light.mjs"),
    import("shiki/themes/github-dark.mjs"),
  ]).then(([core, engine, json, githubLight, githubDark]) =>
    core.createHighlighterCore({
      engine: engine.createJavaScriptRegexEngine(),
      langs: [json.default],
      themes: [githubLight.default, githubDark.default],
    }),
  ) as Promise<HighlighterGeneric<BundledLanguage, BundledTheme>>;

  highlighterCache.set(language, highlighterPromise);
  return highlighterPromise;
}

export function createRawTokens(code: string): TokenizedCode {
  return {
    bg: "transparent",
    fg: "inherit",
    tokens: code.split("\n").map((line) =>
      line === ""
        ? []
        : [
            {
              color: "inherit",
              content: line,
            } as ThemedToken,
          ],
    ),
  };
}

/**
 * Returns cached tokens synchronously and publishes the first async Shiki
 * result to every mounted consumer of the same source snapshot.
 */
export function highlightCode(
  code: string,
  language: BundledLanguage,
  callback?: (result: TokenizedCode) => void,
): TokenizedCode | null {
  const tokensCacheKey = getTokensCacheKey(code, language);
  const cached = tokensCache.get(tokensCacheKey);

  if (cached) {
    return cached;
  }

  if (callback) {
    if (!subscribers.has(tokensCacheKey)) {
      subscribers.set(tokensCacheKey, new Set());
    }
    subscribers.get(tokensCacheKey)?.add(callback);
  }

  void getHighlighter(language)
    .then((highlighter) => {
      const availableLangs = highlighter.getLoadedLanguages();
      const langToUse = availableLangs.includes(language) ? language : "json";
      const result = highlighter.codeToTokens(code, {
        lang: langToUse,
        themes: {
          dark: "github-dark",
          light: "github-light",
        },
      });
      const tokenized: TokenizedCode = {
        bg: result.bg ?? "transparent",
        fg: result.fg ?? "inherit",
        tokens: result.tokens,
      };

      tokensCache.set(tokensCacheKey, tokenized);

      const listeners = subscribers.get(tokensCacheKey);
      if (listeners) {
        for (const listener of listeners) {
          listener(tokenized);
        }
        subscribers.delete(tokensCacheKey);
      }
    })
    .catch((error) => {
      console.error("Failed to highlight code:", error);
      subscribers.delete(tokensCacheKey);
    });

  return null;
}
