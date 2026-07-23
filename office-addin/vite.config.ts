import { defineConfig } from "vite";
import { getHttpsServerOptions } from "office-addin-dev-certs";

export default defineConfig(async ({ command }) => {
  const https = command === "serve" ? await getHttpsServerOptions() : undefined;
  return {
    base: "/",
    server: {
      host: "127.0.0.1",
      port: 3000,
      strictPort: true,
      https,
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8000",
          changeOrigin: false,
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
      rollupOptions: {
        input: "taskpane.html",
      },
    },
  };
});
