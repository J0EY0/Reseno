import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      include: ["tests/**/*.test.{ts,tsx}"],
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      server: {
        deps: {
          inline: ["@lobehub/icons", "@lobehub/ui"],
        },
      },
      clearMocks: true,
      restoreMocks: true,
    },
  }),
);
