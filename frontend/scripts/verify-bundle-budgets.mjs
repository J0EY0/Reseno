#!/usr/bin/env node

import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { build } from "vite";

import {
  DEFAULT_DYNAMIC_ENTRY_GZIP_BYTES,
  DEFAULT_DYNAMIC_ENTRY_RAW_BYTES,
  KIB,
  MAX_CHUNK_GZIP_BYTES,
  MAX_CHUNK_RAW_BYTES,
  MAX_SHELL_CSS_GZIP_BYTES,
  MAX_SHELL_CSS_RAW_BYTES,
  RATCHET_THRESHOLD,
  conditionalFontCssBudgets,
  routeBudgets,
} from "./bundle-budget-config.mjs";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDirectory, "..");

function formatKiB(bytes) {
  return `${(bytes / KIB).toFixed(1)} KiB`;
}

function getStableChunkName(manifestKey, manifestEntry) {
  if (manifestEntry.src) {
    return manifestEntry.src;
  }

  if (manifestKey === "index.html" || !manifestKey.startsWith("_")) {
    return manifestKey;
  }

  return (
    manifestEntry.name ?? manifestKey.replace(/-[A-Za-z0-9_-]+\.js$/, ".js")
  );
}

function collectStaticClosure(manifest, roots) {
  const visitedKeys = new Set();
  const missingKeys = new Set();

  function visit(manifestKey) {
    if (visitedKeys.has(manifestKey)) {
      return;
    }

    const entry = manifest[manifestKey];
    if (!entry) {
      missingKeys.add(manifestKey);
      return;
    }

    visitedKeys.add(manifestKey);
    for (const importedKey of entry.imports ?? []) {
      visit(importedKey);
    }
  }

  for (const root of roots) {
    visit(root);
  }

  return { visitedKeys, missingKeys };
}

async function measureJavaScriptFiles(outputDirectory, manifest) {
  const measurements = new Map();

  for (const entry of Object.values(manifest)) {
    if (!entry.file?.endsWith(".js") || measurements.has(entry.file)) {
      continue;
    }

    const contents = await readFile(path.join(outputDirectory, entry.file));
    measurements.set(entry.file, {
      rawBytes: contents.byteLength,
      gzipBytes: gzipSync(contents).byteLength,
    });
  }

  return measurements;
}

async function measureOutputFile(outputDirectory, emittedFile) {
  const contents = await readFile(path.join(outputDirectory, emittedFile));
  return {
    rawBytes: contents.byteLength,
    gzipBytes: gzipSync(contents).byteLength,
  };
}

function collectClosureCssFiles(manifest, manifestKeys) {
  const files = new Set();

  for (const manifestKey of manifestKeys) {
    const entry = manifest[manifestKey];

    if (entry?.file?.endsWith(".css")) {
      files.add(entry.file);
    }
    for (const cssFile of entry?.css ?? []) {
      files.add(cssFile);
    }
  }

  return files;
}

async function measureFileSet(outputDirectory, files) {
  let rawBytes = 0;
  let gzipBytes = 0;

  for (const file of files) {
    const measurement = await measureOutputFile(outputDirectory, file);
    rawBytes += measurement.rawBytes;
    gzipBytes += measurement.gzipBytes;
  }

  return { rawBytes, gzipBytes };
}

function measureClosure(manifest, measurements, manifestKeys) {
  const files = new Set();
  let rawBytes = 0;
  let gzipBytes = 0;

  for (const manifestKey of manifestKeys) {
    const file = manifest[manifestKey]?.file;
    if (!file?.endsWith(".js") || files.has(file)) {
      continue;
    }

    const measurement = measurements.get(file);
    if (!measurement) {
      throw new Error(
        `Missing measurement for emitted JavaScript file: ${file}`,
      );
    }

    files.add(file);
    rawBytes += measurement.rawBytes;
    gzipBytes += measurement.gzipBytes;
  }

  return { chunkCount: files.size, rawBytes, gzipBytes };
}

function collectUniqueChunkResults(manifest, measurements) {
  const chunksByFile = new Map();

  for (const [manifestKey, entry] of Object.entries(manifest)) {
    if (!entry.file?.endsWith(".js") || chunksByFile.has(entry.file)) {
      continue;
    }

    chunksByFile.set(entry.file, {
      name: getStableChunkName(manifestKey, entry),
      ...measurements.get(entry.file),
    });
  }

  return [...chunksByFile.values()].sort(
    (left, right) => right.rawBytes - left.rawBytes,
  );
}

function collectFirstPartyDynamicEntries(manifest, measurements) {
  return Object.entries(manifest)
    .filter(
      ([manifestKey, entry]) =>
        manifestKey.startsWith("src/") &&
        entry.isDynamicEntry &&
        entry.file?.endsWith(".js"),
    )
    .map(([manifestKey, entry]) => ({
      manifestKey,
      ...measurements.get(entry.file),
    }))
    .sort((left, right) => right.rawBytes - left.rawBytes);
}

async function verifyBundleBudgets() {
  const temporaryOutput = await mkdtemp(
    path.join(tmpdir(), "reseno-bundle-budgets-"),
  );

  try {
    await build({
      root: frontendRoot,
      logLevel: "warn",
      build: {
        emptyOutDir: true,
        manifest: true,
        outDir: temporaryOutput,
        write: true,
      },
    });

    const manifestPath = path.join(temporaryOutput, ".vite", "manifest.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    const measurements = await measureJavaScriptFiles(
      temporaryOutput,
      manifest,
    );
    const failures = [];

    const shellClosure = collectStaticClosure(manifest, ["index.html"]);
    if (shellClosure.missingKeys.size > 0) {
      failures.push("shell CSS: index.html is missing from the Vite manifest");
    }
    const shellCssFiles = collectClosureCssFiles(
      manifest,
      shellClosure.visitedKeys,
    );
    const shellCssMeasurement = await measureFileSet(
      temporaryOutput,
      shellCssFiles,
    );

    console.log("Shell CSS:");
    console.log(
      `  ${formatKiB(shellCssMeasurement.rawBytes)} raw / ${formatKiB(shellCssMeasurement.gzipBytes)} gzip (${shellCssFiles.size} files)`,
    );
    if (shellCssMeasurement.rawBytes > MAX_SHELL_CSS_RAW_BYTES) {
      failures.push(
        `shell CSS: raw ${formatKiB(shellCssMeasurement.rawBytes)} exceeds ${formatKiB(MAX_SHELL_CSS_RAW_BYTES)}`,
      );
    }
    if (shellCssMeasurement.gzipBytes > MAX_SHELL_CSS_GZIP_BYTES) {
      failures.push(
        `shell CSS: gzip ${formatKiB(shellCssMeasurement.gzipBytes)} exceeds ${formatKiB(MAX_SHELL_CSS_GZIP_BYTES)}`,
      );
    }
    if (
      shellCssMeasurement.rawBytes <=
        MAX_SHELL_CSS_RAW_BYTES * RATCHET_THRESHOLD ||
      shellCssMeasurement.gzipBytes <=
        MAX_SHELL_CSS_GZIP_BYTES * RATCHET_THRESHOLD
    ) {
      failures.push(
        "shell CSS: is at least 5% below its ceiling; ratchet the exact ceiling down",
      );
    }

    console.log("\nConditional resume font CSS:");
    for (const budget of conditionalFontCssBudgets) {
      const matches = Object.entries(manifest).filter(([manifestKey]) =>
        manifestKey.endsWith(budget.manifestKeySuffix),
      );

      if (matches.length !== 1) {
        failures.push(
          `${budget.name}: expected one conditional manifest entry, found ${matches.length}`,
        );
        continue;
      }

      const [, entry] = matches[0];
      if (!entry.file?.endsWith(".css")) {
        failures.push(`${budget.name}: conditional entry must emit CSS`);
        continue;
      }
      if (shellCssFiles.has(entry.file)) {
        failures.push(
          `${budget.name}: must not be part of the shell CSS closure`,
        );
      }

      const measurement = await measureOutputFile(temporaryOutput, entry.file);
      console.log(
        `  ${budget.name}: ${formatKiB(measurement.rawBytes)} raw / ${formatKiB(measurement.gzipBytes)} gzip`,
      );
      if (measurement.rawBytes > budget.maxRawBytes) {
        failures.push(
          `${budget.name}: raw CSS ${formatKiB(measurement.rawBytes)} exceeds ${formatKiB(budget.maxRawBytes)}`,
        );
      }
      if (measurement.gzipBytes > budget.maxGzipBytes) {
        failures.push(
          `${budget.name}: gzip CSS ${formatKiB(measurement.gzipBytes)} exceeds ${formatKiB(budget.maxGzipBytes)}`,
        );
      }
    }

    const chunkResults = collectUniqueChunkResults(manifest, measurements);

    for (const chunk of chunkResults) {
      if (chunk.rawBytes > MAX_CHUNK_RAW_BYTES) {
        failures.push(
          `chunk ${chunk.name}: raw ${formatKiB(chunk.rawBytes)} exceeds ${formatKiB(MAX_CHUNK_RAW_BYTES)}`,
        );
      }
      if (chunk.gzipBytes > MAX_CHUNK_GZIP_BYTES) {
        failures.push(
          `chunk ${chunk.name}: gzip ${formatKiB(chunk.gzipBytes)} exceeds ${formatKiB(MAX_CHUNK_GZIP_BYTES)}`,
        );
      }
    }

    console.log("Largest JavaScript chunks:");
    for (const chunk of chunkResults.slice(0, 5)) {
      console.log(
        `  ${chunk.name}: ${formatKiB(chunk.rawBytes)} raw / ${formatKiB(chunk.gzipBytes)} gzip`,
      );
    }

    const dynamicEntries = collectFirstPartyDynamicEntries(
      manifest,
      measurements,
    );
    console.log("\nFirst-party dynamic entries:");
    for (const entry of dynamicEntries) {
      console.log(
        `  ${entry.manifestKey}: ${formatKiB(entry.rawBytes)} raw / ${formatKiB(entry.gzipBytes)} gzip`,
      );

      if (entry.rawBytes > DEFAULT_DYNAMIC_ENTRY_RAW_BYTES) {
        failures.push(
          `dynamic entry ${entry.manifestKey}: raw ${formatKiB(entry.rawBytes)} exceeds ${formatKiB(DEFAULT_DYNAMIC_ENTRY_RAW_BYTES)}`,
        );
      }
      if (entry.gzipBytes > DEFAULT_DYNAMIC_ENTRY_GZIP_BYTES) {
        failures.push(
          `dynamic entry ${entry.manifestKey}: gzip ${formatKiB(entry.gzipBytes)} exceeds ${formatKiB(DEFAULT_DYNAMIC_ENTRY_GZIP_BYTES)}`,
        );
      }
    }

    console.log("\nRoute JavaScript closures:");
    for (const budget of routeBudgets) {
      const { visitedKeys, missingKeys } = collectStaticClosure(
        manifest,
        budget.roots,
      );

      if (missingKeys.size > 0) {
        failures.push(
          `route ${budget.name}: manifest is missing stable source key(s): ${[...missingKeys].join(", ")}`,
        );
        console.log(`  ${budget.name}: unable to measure`);
        continue;
      }

      for (const forbiddenEntry of budget.forbiddenStaticEntries ?? []) {
        if (visitedKeys.has(forbiddenEntry)) {
          failures.push(
            `route ${budget.name}: static closure must not include ${forbiddenEntry}`,
          );
        }
      }

      const measurement = measureClosure(manifest, measurements, visitedKeys);
      console.log(
        `  ${budget.name}: ${formatKiB(measurement.gzipBytes)} gzip / ${formatKiB(measurement.rawBytes)} raw (${measurement.chunkCount} chunks, limit ${formatKiB(budget.maxGzipBytes)} gzip)`,
      );

      if (measurement.gzipBytes > budget.maxGzipBytes) {
        failures.push(
          `route ${budget.name}: gzip closure ${formatKiB(measurement.gzipBytes)} exceeds ${formatKiB(budget.maxGzipBytes)}`,
        );
      } else if (
        measurement.gzipBytes <=
        budget.maxGzipBytes * RATCHET_THRESHOLD
      ) {
        failures.push(
          `route ${budget.name}: gzip closure is at least 5% below ${formatKiB(budget.maxGzipBytes)}; ratchet the route ceiling down`,
        );
      }
    }

    if (failures.length > 0) {
      console.error("\nBundle budget verification failed:");
      for (const failure of failures) {
        console.error(`  - ${failure}`);
      }
      process.exitCode = 1;
      return;
    }

    console.log("\nBundle budgets verified.");
  } finally {
    await rm(temporaryOutput, { force: true, recursive: true });
  }
}

try {
  await verifyBundleBudgets();
} catch (error) {
  console.error("Bundle budget verification could not complete.");
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
