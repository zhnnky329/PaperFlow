// Opt-in Chrome inspection after quality_gate.py. Does not install/use extensions.
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import fs from "node:fs";
const input = process.argv[2];
const origin = process.argv[3] || "http://127.0.0.1:8010";
const output = process.argv[4] || "docs/validation/quality-browser.json";
const report = JSON.parse(fs.readFileSync(input, "utf8"));
fs.mkdirSync("docs/validation/quality", { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const results = [];
try {
  for (const sample of report.samples) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const row = { arxiv_id: sample.arxiv_id, reader: sample.reader, read_frog: "NOT RUN" };
    try {
      if (sample.status !== "succeeded") throw new Error("conversion/import failed");
      const url = sample.reader === "marker"
        ? `${origin}/read/${sample.paper_id}/html` : sample.official_html_url;
      const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
      if (!response?.ok()) throw new Error(`HTTP ${response?.status()}`);
      if (sample.reader === "marker") {
        await page.waitForFunction(() => document.querySelectorAll("article math:not(:has(*))").length === 0);
        await page.waitForFunction(() => Array.from(document.images).every(i => i.complete));
        await page.waitForTimeout(900);
        await page.evaluate(() => { document.documentElement.dataset.theme = "light"; scrollTo(0, 0); });
        row.dom = await page.evaluate(() => ({
          paragraphs: document.querySelectorAll("article p").length,
          images: document.querySelectorAll("article img").length,
          brokenImages: Array.from(document.images).filter(i => !i.naturalWidth).length,
          renderedMath: document.querySelectorAll("article .katex").length,
          math: document.querySelectorAll("article [data-math-source]").length +
            Array.from(document.querySelectorAll("article math")).filter(node => !node.closest(".katex")).length,
          katexErrors: document.querySelectorAll(".katex-error").length,
          tables: document.querySelectorAll("article table").length,
          headings: document.querySelectorAll("aside a").length,
          articleWidth: Math.round(document.querySelector("article").getBoundingClientRect().width),
          documentWidth: document.documentElement.scrollWidth,
        }));
        const name = `docs/validation/quality/${sample.arxiv_id}`;
        await page.screenshot({ path: name + "-top.png" });
        const links = page.locator("aside a");
        if (await links.count()) {
          await links.nth(Math.min(3, (await links.count()) - 1)).click();
          await page.waitForTimeout(900);
          const saved = await page.evaluate(() => scrollY);
          await page.goto(url);
          await page.waitForTimeout(1200);
          const restored = await page.evaluate(() => scrollY);
          row.progress = Math.abs(saved - restored) < 80 ? "PASS" : "FAIL";
        } else row.progress = "NOT RUN";
        await page.screenshot({ path: name + "-middle.png" });
        const math = page.locator("article [data-math-source],article math");
        if (await math.count()) {
          await math.first().scrollIntoViewIfNeeded();
          await page.screenshot({ path: name + "-math.png" });
        }
        for (const [kind, selector] of [["figure", "article img"], ["table", "article table"]]) {
          const element = page.locator(selector).first();
          if (await element.count()) {
            await element.scrollIntoViewIfNeeded();
            await page.screenshot({ path: name + "-" + kind + ".png" });
          }
        }
        if (await links.count()) {
          await links.last().click();
          await page.screenshot({ path: name + "-last-section.png" });
        }
        row.status = (row.dom.math > 0 && row.dom.renderedMath === 0) || row.dom.brokenImages || row.dom.katexErrors || row.dom.documentWidth > 1280 || row.progress === "FAIL" ? "FAIL" : "PASS";
      } else {
        await page.waitForSelector(".ltx_document", { timeout: 30000 });
        row.status = "PASS";
        row.paragraphs = await page.locator(".ltx_para").count();
        await page.screenshot({ path: `docs/validation/quality/${sample.arxiv_id}-official.png` });
      }
      row.pageErrors = errors.length;
      if (errors.length && sample.reader === "marker") row.status = "FAIL";
    } catch (error) {
      row.status = "FAIL";
      row.error = error.message;
    } finally { await page.close(); }
    results.push(row);
    fs.writeFileSync(output, JSON.stringify({ read_frog: "NOT RUN", visual_quality: "NOT RUN", samples: results }, null, 2) + "\n");
    console.log(row);
  }
} finally { await browser.close(); }
if (results.some(row => row.status === "FAIL")) process.exitCode = 1;
