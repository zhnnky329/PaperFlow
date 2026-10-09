// Actual public-PDF/Finder Gate; use an isolated data directory only.
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import fs from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";
const origin = process.argv[2] || "http://127.0.0.1:8010";
const pdf = process.argv[3];
if (!pdf)
  throw new Error("Provide a real public PDF path as the second argument");
const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
    colorScheme: "light",
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(origin);
  await page.locator(".paper-row").first().waitFor();
  const existing = await page.request
    .get(origin + "/api/v1/collections")
    .then((r) => r.json());
  const previous = existing.find((c) => c.name === "SLAM 研究");
  if (!previous) {
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "新建文件夹", exact: true })
      .click();
    await page.getByLabel("名称", { exact: true }).fill("SLAM 研究");
    await page.getByRole("button", { name: "保存", exact: true }).click();
  } else await page.goto(`${origin}/?folder=${previous.id}`);
  await page.getByRole("heading", { name: /SLAM 研究/ }).waitFor();
  await page.getByRole("button", { name: "Add Paper", exact: true }).click();
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByRole("button", { name: "选择 PDF 文件", exact: true }).click(),
  ]);
  await chooser.setFiles(pdf);
  await page
    .getByRole("status")
    .filter({ hasText: /已存在|导入成功/ })
    .waitFor();
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.locator(".paper-row").first().waitFor();
  await page.waitForFunction(
    async () =>
      (await (await fetch("/api/v1/settings")).json()).folder_sync.status ===
      "succeeded",
  );
  const collection = await page.request
    .get(origin + "/api/v1/collections")
    .then((r) => r.json())
    .then((rows) => rows.find((c) => c.name === "SLAM 研究"));
  const files = (await fs.readdir(collection.finder_path)).filter((name) =>
    name.endsWith(".pdf"),
  );
  assert.equal(files.length, 1);
  const copy = path.join(collection.finder_path, files[0]);
  assert.deepEqual(await fs.readFile(copy), await fs.readFile(pdf));
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
  });
  await page.screenshot({
    path: "docs/validation/ui/folder-real.png",
    animations: "disabled",
  });
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/reveal") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "在 Finder 中打开", exact: true })
    .click();
  const revealed = await response;
  assert.equal(revealed.status(), 200);
  assert.deepEqual(await revealed.json(), { opened: true });
  await page.goto(origin);
  await page.locator(".folder-card").first().waitFor();
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
  });
  await page.screenshot({
    path: "docs/validation/ui/folders-real.png",
    animations: "disabled",
  });
  assert.equal(errors.length, 0);
  const report = {
    origin,
    folder: collection.name,
    finderPath: collection.finder_path,
    copies: files.length,
    equalToOriginal: true,
    nativeOpen: "PASS",
    finderWindowVisualInspection: "NOT RUN",
    pageErrors: errors,
    readFrog: "NOT RUN",
  };
  await fs.writeFile(
    "docs/validation/ui/folders-report.json",
    JSON.stringify(report, null, 2) + "\n",
  );
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
