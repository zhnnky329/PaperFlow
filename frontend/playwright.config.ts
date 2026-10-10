import { defineConfig } from "@playwright/test";
import path from "node:path";
import os from "node:os";
export default defineConfig({
  testDir: "../tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: "http://127.0.0.1:8000",
    viewport: { width: 1280, height: 900 },
    channel: "chrome",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "../.venv/bin/python ../scripts/run.py serve --no-open",
    url: "http://127.0.0.1:8000/api/v1/health",
    reuseExistingServer: false,
    env: {
      PAPERFLOW_DATA_DIR: path.join(os.tmpdir(), `paperflow-e2e-${Date.now()}`),
      PAPERFLOW_MARKER_EXECUTABLE: "/missing/marker",
    },
  },
});
