import { defineConfig } from "@playwright/test";
import path from "node:path";
import os from "node:os";
const port = Number(process.env.PAPERFLOW_E2E_PORT || 8873);
const baseURL = `http://127.0.0.1:${port}`;
const python = (process.env.PAPERFLOW_PYTHON || "../.venv/bin/python").replaceAll("'", "'\"'\"'");
export default defineConfig({
  testDir: "../tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL,
    viewport: { width: 1280, height: 900 },
    channel: process.env.PAPERFLOW_BROWSER_CHANNEL || "chrome",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `'${python}' ../scripts/run.py serve --no-open`,
    url: `${baseURL}/api/v1/health`,
    reuseExistingServer: false,
    env: {
      PAPERFLOW_DATA_DIR: path.join(os.tmpdir(), `paperflow-e2e-${Date.now()}`),
      PAPERFLOW_MARKER_EXECUTABLE: "/missing/marker",
      PAPERFLOW_PORT: String(port),
      PAPERFLOW_DISCOVERY_ONLINE: "false",
      PAPERFLOW_DEEPSEEK_API_KEY: "",
    },
  },
});
