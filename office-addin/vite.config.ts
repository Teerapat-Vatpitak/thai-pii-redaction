import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "vite";
import { getHttpsServerOptions } from "office-addin-dev-certs";

type HttpsServerOptions = Awaited<ReturnType<typeof getHttpsServerOptions>>;

interface HttpsDependencies {
  homeDirectory: () => string;
  provision: typeof getHttpsServerOptions;
  readFile: (path: string) => Buffer;
}

const CERTIFICATE_DIRECTORY_NAME = ".office-addin-dev-certs";
const CERTIFICATE_FILE_NAMES = {
  ca: "ca.crt",
  cert: "localhost.crt",
  key: "localhost.key",
} as const;

export async function resolveHttpsOptions(
  command: string,
  environment: Readonly<Record<string, string | undefined>>,
  dependencies: HttpsDependencies = {
    homeDirectory: homedir,
    provision: getHttpsServerOptions,
    readFile: (path) => readFileSync(path),
  },
): Promise<HttpsServerOptions | undefined> {
  if (command !== "serve") {
    return undefined;
  }

  if (environment.AIGUARD_OFFICE_EXISTING_CERTS_ONLY !== "1") {
    return dependencies.provision();
  }

  const certificateDirectory = join(
    dependencies.homeDirectory(),
    CERTIFICATE_DIRECTORY_NAME,
  );

  return {
    ca: dependencies.readFile(
      join(certificateDirectory, CERTIFICATE_FILE_NAMES.ca),
    ),
    cert: dependencies.readFile(
      join(certificateDirectory, CERTIFICATE_FILE_NAMES.cert),
    ),
    key: dependencies.readFile(
      join(certificateDirectory, CERTIFICATE_FILE_NAMES.key),
    ),
  };
}

export default defineConfig(async ({ command }) => {
  const https = await resolveHttpsOptions(command, process.env);
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
