import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backendTarget =
  process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8000";
const viteCacheDir = process.env.RESENO_VITE_CACHE_DIR ?? "node_modules/.vite";
const __dirname = path.dirname(fileURLToPath(import.meta.url));

function isNodePackage(id: string, packageName: string) {
  const escapedPackageName = packageName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const packagePattern = new RegExp(
    `/node_modules/(?:\\.pnpm/[^/]+/node_modules/)?${escapedPackageName}/`,
  );

  return packagePattern.test(id);
}

// https://vite.dev/config/
export default defineConfig({
  cacheDir: viteCacheDir,
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 480,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "vendor-runtime",
              priority: 20,
              test: (id) =>
                id.includes("react-jsx-runtime") ||
                id.includes("/react/jsx-runtime") ||
                id.includes("/react/cjs/react-jsx-runtime") ||
                id.includes("/axios/dist/browser/axios.cjs") ||
                [
                  "react",
                  "react-dom",
                  "react-error-boundary",
                  "react-router",
                  "react-router-dom",
                  "scheduler",
                  "@radix-ui/react-slot",
                  "@radix-ui/react-compose-refs",
                  "class-variance-authority",
                  "clsx",
                  "sonner",
                  "tailwind-merge",
                ].some((name) => isNodePackage(id, name)),
            },
            {
              name: "vendor-ui",
              test: (id) =>
                id.includes("/@floating-ui/") ||
                isNodePackage(id, "@radix-ui/react-tooltip") ||
                isNodePackage(id, "@radix-ui/react-focus-scope") ||
                isNodePackage(id, "@radix-ui/react-focus-guards") ||
                isNodePackage(id, "aria-hidden") ||
                isNodePackage(id, "react-remove-scroll"),
            },
          ],
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
