import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { hasImport, parseSource } from "./source-analysis.mjs";

const frontendRoot = new URL("../", import.meta.url);

async function readText(path) {
  return readFile(new URL(path, frontendRoot), "utf8");
}

function collectJsonShape(value, path = "$") {
  if (Array.isArray(value)) {
    return [
      `${path}:array`,
      ...value.flatMap((item, index) =>
        collectJsonShape(item, `${path}[${index}]`),
      ),
    ];
  }

  if (value && typeof value === "object") {
    return [
      `${path}:object`,
      ...Object.keys(value)
        .sort()
        .flatMap((key) => collectJsonShape(value[key], `${path}.${key}`)),
    ];
  }

  return [`${path}:${typeof value}`];
}

const [i18nSource, messageModelSource, enSource, zhSource] = await Promise.all(
  [
    "src/i18n/index.ts",
    "src/components/copilot/copilot-message-model.ts",
    "src/i18n/locales/en.json",
    "src/i18n/locales/zh.json",
  ].map(readText),
);

const i18nFile = parseSource(i18nSource, "index.ts");
assert.ok(
  hasImport(i18nFile, "./locales/en.json"),
  "The default English locale must remain synchronously available at bootstrap.",
);
assert.equal(
  hasImport(i18nFile, "./locales/zh.json"),
  false,
  "The non-default Chinese catalog must not be a static bootstrap dependency.",
);
assert.ok(
  hasImport(i18nFile, "./locales/zh.json", { dynamic: true }),
  "The Chinese catalog must use a statically analyzable literal dynamic import.",
);

assert.deepEqual(
  collectJsonShape(JSON.parse(zhSource)),
  collectJsonShape(JSON.parse(enSource)),
  "English and Chinese message catalogs must keep the same structural contract.",
);

assert.doesNotMatch(
  messageModelSource,
  /getMessagesSync/,
  "The Agent message model must not pull every locale into bootstrap synchronously.",
);

const catalogs = [JSON.parse(enSource), JSON.parse(zhSource)];
for (const [key, english, chinese] of [
  ["canvasPage", "Page 1 / 3", "第 1 / 3 页"],
  ["maxTokensAuto", "Auto", "自动"],
  [
    "apiMessages.AGENT_DRAFT_DECISION_CONFLICT",
    "This draft was already resolved elsewhere.",
    "该草稿已在其他位置处理",
  ],
  [
    "apiMessages.MODEL_CONFIG_MAX_TOKENS_INVALID",
    "Enter an integer greater than 0.",
    "请输入大于 0 的整数",
  ],
  [
    "apiMessages.MODEL_CONFIG_MAX_TOKENS_EXCEEDS_LIMIT",
    "The output limit exceeds this model's maximum.",
    "输出上限超过该模型允许的最大值",
  ],
  [
    "apiMessages.MODEL_CONFIG_THINKING_MODE_INVALID",
    "Select a valid thinking mode.",
    "请选择有效的推理模式",
  ],
  [
    "apiMessages.MODEL_CONFIG_THINKING_MODE_UNSUPPORTED",
    "This model cannot turn reasoning off. Select Auto instead.",
    "该模型无法关闭推理，请改用自动模式",
  ],
]) {
  const actual = catalogs.map((messages) => {
    const value = key.split(".").reduce((entry, part) => entry[part], messages);
    return key === "canvasPage"
      ? value.replace("{current}", "1").replace("{total}", "3")
      : value;
  });
  assert.deepEqual(
    actual,
    [english, chinese],
    `${key} must retain its localized contract.`,
  );
}
for (const messages of catalogs) {
  assert.equal(
    Object.hasOwn(messages, "thinkingEnabled"),
    false,
    "Model settings must not retain copy for the removed Thinking toggle.",
  );
}
console.log("i18n conditional-loading checks passed.");
