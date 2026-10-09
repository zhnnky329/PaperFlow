// Optional actual browser inspection against scripts/validate_real.py output.
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import fs from "node:fs";
const report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const origin = process.argv[3] || "http://127.0.0.1:8010";
const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(origin + "/");
  await page.waitForSelector(".paper-row");
  await page.screenshot({ path: "docs/validation/library-real.png" });
  await page.goto(`${origin}/read/${report.paper_id}/html`);
  await page.waitForFunction(
    () => document.querySelectorAll(".katex").length > 0,
  );
  await page.waitForFunction(() =>
    Array.from(document.images).every((i) => i.complete && i.naturalWidth > 0),
  );
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
    scrollTo(0, 0);
  });
  await page.waitForTimeout(800);
  await page.screenshot({ path: "docs/validation/html-real.png" });
  const counts = await page.evaluate(() => ({
    images: document.querySelectorAll("article img").length,
    math: document.querySelectorAll("article [data-math-source]").length,
    katex: document.querySelectorAll(".katex").length,
    katexErrors: document.querySelectorAll(".katex-error").length,
    tables: document.querySelectorAll("article table").length,
    headings: document.querySelectorAll("aside a").length,
    brokenImages: Array.from(document.images).filter((i) => !i.naturalWidth)
      .length,
  }));
  if (counts.katexErrors || counts.brokenImages || counts.math !== 9)
    throw new Error("Actual article render check failed");
  const links = page.locator("aside a");
  await links.nth(Math.min(4, (await links.count()) - 1)).click();
  await page.waitForTimeout(1000);
  const position = await page.evaluate(() => ({
    scroll: scrollY,
    hash: location.hash,
  }));
  await page.goto(`${origin}/read/${report.paper_id}/html`);
  await page.waitForTimeout(1100);
  const restored = await page.evaluate(() => scrollY);
  if (position.scroll > 100 && restored < 100)
    throw new Error("HTML scroll did not restore");
  if ((await page.locator("html").getAttribute("data-theme")) !== "dark")
    await page.locator("#theme").click();
  await page.screenshot({ path: "docs/validation/html-dark-real.png" });
  const math = page.locator("article [data-math-source]").first();
  await math.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "docs/validation/html-math-real.png" });
  if (errors.length) throw new Error(errors.join(";"));
  const result = {
    ...counts,
    consoleErrors: errors.length,
    toc: "PASS",
    progress: restored > 100 ? "PASS" : "NOT RUN",
    readFrog: "NOT RUN",
  };
  fs.writeFileSync(
    "docs/validation/html-browser.json",
    JSON.stringify(result, null, 2) + "\n",
  );
  console.log(result);
} finally {
  await browser.close();
}
