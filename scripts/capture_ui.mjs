// Visual QA uses an isolated Library containing actual public PDFs.
// Usage: node scripts/capture_ui.mjs http://127.0.0.1:8010 [empty-library-origin]
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import fs from "node:fs";
const origin = process.argv[2] || "http://127.0.0.1:8010";
const emptyOrigin = process.argv[3];
const directory = "docs/validation/ui";
fs.mkdirSync(directory, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
const checks = [];
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
    colorScheme: "light",
  });
  page.on("pageerror", (error) => errors.push(error.message));
  async function theme(value) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, value);
  }
  async function capture(name) {
    // Let Chrome finish layout/compositing after theme and viewport changes.
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await page.mouse.move(1279, 899);
    await page.screenshot({
      path: `${directory}/${name}.png`,
      animations: "disabled",
    });
  }
  async function noOverflow(name) {
    const excess = await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    );
    if (excess > 1) throw new Error(`${name}: viewport overflow ${excess}px`);
    checks.push(`${name}: no horizontal overflow`);
  }
  await page.goto(origin);
  await page.locator(".paper-row").first().waitFor();
  await theme("light");
  await noOverflow("library desktop");
  await capture("library-light");
  await page.getByLabel("搜索论文").fill("paperflow-ui-no-match-20261009");
  await page.getByRole("heading", { name: "没有匹配的论文" }).waitFor();
  await capture("search-empty");
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  await page.locator(".paper-row").first().waitFor();
  checks.push("empty search clears filters and restores actual Library: PASS");
  await page.getByRole("button", { name: "Add Paper", exact: true }).click();
  await page.getByRole("dialog", { name: "Add Paper" }).waitFor();
  await capture("import-light");
  await page.getByRole("button", { name: "arXiv Link", exact: true }).click();
  await page.getByPlaceholder("https://arxiv.org/abs/1706.03762").waitFor();
  await capture("arxiv-light");
  await page.keyboard.press("Escape");
  if (await page.locator("dialog[open]").count())
    throw new Error("Escape did not dismiss import");
  checks.push("import PDF/arXiv controls and Escape: PASS");
  await theme("dark");
  await capture("library-dark");
  await page.getByRole("button", { name: "Add Paper", exact: true }).click();
  await capture("import-dark");
  await page.keyboard.press("Escape");
  await page.goto(origin + "/settings");
  await page
    .getByRole("heading", { name: "Appearance", exact: true })
    .waitFor();
  await theme("dark");
  await capture("settings-dark");
  await page.goto(origin);
  await page.locator(".paper-row").first().waitFor();
  await theme("light");
  const localRow = page
    .locator(".paper-row")
    .filter({ has: page.locator('a[href^="/read/"]') })
    .first();
  const pdfHref = await localRow
    .locator(".paper-actions a")
    .filter({ hasText: /^PDF$/ })
    .first()
    .getAttribute("href");
  const htmlHref = await page
    .locator(".paper-actions a")
    .filter({ hasText: /^HTML$/ })
    .first()
    .getAttribute("href");
  if (!pdfHref || !htmlHref)
    throw new Error("QA Library needs actual PDF and HTML documents");
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow("library mobile");
  if (!(await page.locator(".paper-actions").first().isVisible()))
    throw new Error("Mobile actions hidden");
  await capture("library-mobile");
  checks.push("mobile PDF/HTML/status actions visible: PASS");
  await page.getByRole("button", { name: "Add Paper", exact: true }).click();
  await noOverflow("import mobile");
  await capture("import-mobile");
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(origin + pdfHref);
  await page.locator(".textLayer span").first().waitFor({ timeout: 30000 });
  await theme("light");
  await noOverflow("PDF desktop");
  await capture("pdf-light");
  checks.push("PDF.js rendered canvas and text: PASS");
  await page.goto(origin + htmlHref);
  await page.locator("article .katex").first().waitFor();
  await page.waitForFunction(() =>
    Array.from(document.images).every((i) => i.complete && i.naturalWidth > 0),
  );
  await theme("light");
  await page.evaluate(() => scrollTo(0, 0));
  await noOverflow("HTML desktop");
  await capture("html-light");
  await theme("dark");
  await capture("html-dark");
  checks.push("actual HTML formulas and images: PASS");
  await page.locator("aside a").nth(3).click();
  await page.waitForFunction(() => scrollY > 100);
  // The reader saves progress on a 700ms debounce.
  await page.waitForTimeout(1100);
  await page.reload();
  await page.waitForFunction(() => scrollY > 100);
  checks.push("HTML TOC navigation and progress restore: PASS");
  await page.emulateMedia({ reducedMotion: "reduce" });
  const duration = await page
    .locator("#theme")
    .evaluate((el) => getComputedStyle(el).transitionDuration);
  if (duration !== "0s")
    throw new Error("Reduced motion did not disable transitions");
  checks.push("reduced motion disables HTML control transitions: PASS");
  if (emptyOrigin) {
    await page.goto(emptyOrigin);
    await page
      .getByRole("heading", { name: "你的下一篇论文，从这里开始" })
      .waitFor();
    await theme("light");
    await capture("empty-light");
    await theme("dark");
    await capture("empty-dark");
  }
  if (errors.length) throw new Error(errors.join("; "));
  const result = {
    browser: browser.version(),
    origin,
    checks,
    pageErrors: errors,
    readFrog: "NOT RUN",
  };
  fs.writeFileSync(
    `${directory}/report.json`,
    JSON.stringify(result, null, 2) + "\n",
  );
  console.log(JSON.stringify(result, null, 2));
} finally {
  await browser.close();
}
