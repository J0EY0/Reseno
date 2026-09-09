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
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (
            id.includes("react-jsx-runtime") ||
            id.includes("/react/jsx-runtime") ||
            id.includes("/react/cjs/react-jsx-runtime")
          ) {
            return "vendor-react";
          }

          if (!id.includes("node_modules")) {
            return;
          }

          if (
            isNodePackage(id, "react") ||
            isNodePackage(id, "react-dom") ||
            isNodePackage(id, "react-router") ||
            isNodePackage(id, "react-router-dom") ||
            isNodePackage(id, "scheduler")
          ) {
            return "vendor-react";
          }
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
