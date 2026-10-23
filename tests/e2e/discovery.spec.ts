import { test, expect } from "../../frontend/node_modules/@playwright/test";
import { execFileSync } from "node:child_process";

const candidateId = "38a9666d-1eb7-42d9-8722-0d8ad866b147";
const title = "Discovery integration fixture: Active Visual Perception";

test("Discover → persisted feedback → existing arXiv Library import", async ({
  page,
  request,
  baseURL,
}) => {
  const storage = await (await request.get("/api/v1/settings")).json();
  expect(storage.data_dir).toContain("paperflow-e2e-");
  const initial = await (
    await request.get("/api/v1/discovery/settings")
  ).json();
  const headers = { "X-PaperFlow": "1", Origin: baseURL! };
  // A test-only recommendation deposited in the isolated SQLite database.
  // This verifies real UI/API persistence and import, not a live AI result.
  execFileSync(process.env.PAPERFLOW_PYTHON || "python3", [
    "-c",
    `
import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
now = datetime.now(timezone.utc).isoformat()
analysis = {"decision":"recommend", "score":91, "matched_directions":["uav"],
            "reason":"集成测试：研究问题与主动视觉方向相关。", "summary":"这是仅用于自动化集成测试的中文总结，验证推荐内容、分析依据与用户反馈的持久化。此记录不代表真实 DeepSeek 分析结果。",
            "basis":"abstract", "source_url":"https://arxiv.org/abs/2610.99991", "tokens_used":321}
with sqlite3.connect(Path(sys.argv[1]) / "paperflow.sqlite3") as db:
    db.execute("INSERT INTO discovery_papers (id,arxiv_id,arxiv_aliases,arxiv_version,title,authors,abstract,categories,published_at,updated_at,source_url,content_hash,analysis_status,analysis,analyzed_at,feedback,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (sys.argv[2],"2610.99991","[]",1,sys.argv[3],json.dumps(["Integration Fixture"]),"Test-only abstract for active visual perception.",json.dumps(["cs.CV","cs.RO"]),now,now,"https://arxiv.org/abs/2610.99991","fixture-content-hash","succeeded",json.dumps(analysis),now,"none",now,now))
    db.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("discovery_seen_at", json.dumps("")))
`,
    storage.data_dir,
    candidateId,
    title,
  ]);
  try {
    await page.goto("/");
    await expect(page.getByLabel("1 篇新增推荐")).toBeVisible();
    await page.getByRole("link", { name: /Discover/ }).click();
    await expect(page.getByRole("heading", { name: /Discover/ })).toBeVisible();
    const paper = page.getByRole("article", { name: title });
    await expect(paper).toBeVisible();
    await expect(
      paper.getByText("仅基于摘要判断", { exact: true }),
    ).toBeVisible();
    await expect(paper.getByText("91", { exact: true })).toBeVisible();
    await expect(page.getByLabel("1 篇新增推荐")).toHaveCount(0);
    await paper.getByRole("button", { name: "稍后阅读", exact: true }).click();
    await expect(
      paper.getByRole("button", { name: "已存稍后阅读", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await page.reload();
    await expect(
      paper.getByRole("button", { name: "已存稍后阅读", exact: true }),
    ).toBeVisible();
    await page.getByLabel("推荐范围").selectOption("interested");
    await expect(paper).toBeVisible();
    await paper.getByRole("button", { name: "不感兴趣", exact: true }).click();
    await page.getByLabel("推荐范围").selectOption("recommended");
    await expect(paper).toHaveCount(0);
    await page.getByLabel("推荐范围").selectOption("dismissed");
    await expect(paper).toBeVisible();
    await paper.getByRole("button", { name: "恢复推荐", exact: true }).click();
    await page.getByLabel("推荐范围").selectOption("recommended");
    await expect(paper).toBeVisible();
    execFileSync(process.env.PAPERFLOW_PYTHON || "python3", [
      "-c",
      `
import sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]) / "paperflow.sqlite3") as db:
    db.execute("UPDATE discovery_papers SET analysis_status='pending' WHERE id=?", (sys.argv[2],))
`,
      storage.data_dir,
      candidateId,
    ]);
    await page.getByLabel("推荐范围").selectOption("history");
    await expect(
      paper.getByText("以下为上次分析，当前版本待重新判断。", { exact: true }),
    ).toBeVisible();
    execFileSync(process.env.PAPERFLOW_PYTHON || "python3", [
      "-c",
      `
import sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]) / "paperflow.sqlite3") as db:
    db.execute("UPDATE discovery_papers SET analysis_status='succeeded' WHERE id=?", (sys.argv[2],))
`,
      storage.data_dir,
      candidateId,
    ]);
    await page.getByLabel("推荐范围").selectOption("recommended");
    await paper
      .getByRole("button", { name: "加入文献库", exact: true })
      .click();
    await expect(
      page.getByRole("status").filter({ hasText: "已加入 Library" }),
    ).toBeVisible();
    await page.getByLabel("推荐范围").selectOption("history");
    await expect(
      paper.getByText("已在 Library", { exact: true }),
    ).toBeVisible();
    await expect(
      paper.getByRole("link", { name: "打开 Library 论文", exact: true }),
    ).toBeVisible();
    const repeated = await request.post(
      `/api/v1/discovery/papers/${candidateId}/import`,
      { headers },
    );
    expect(repeated.ok()).toBe(true);
    expect((await repeated.json()).dedupe).toBe(true);
    await page.getByRole("link", { name: "All papers", exact: true }).click();
    await expect(
      page.getByRole("link", { name: title, exact: true }),
    ).toBeVisible();
    for (const theme of ["light", "dark"]) {
      await request.patch("/api/v1/settings", { headers, data: { theme } });
      await page.goto("/discover");
      await page.getByLabel("推荐范围").selectOption("history");
      await expect(paper).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      for (const width of [1280, 900, 390]) {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate(async () => {
          window.scrollTo(0, 0);
          await new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          );
        });
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
          ),
        ).toBe(true);
        await page.screenshot({
          path: `../docs/validation/discovery-${theme}-${width}.png`,
          fullPage: true,
        });
      }
    }
  } finally {
    const papers = await (
      await request.get("/api/v1/papers?q=" + encodeURIComponent(title))
    ).json();
    for (const paper of papers.items) {
      const deleted = await request.delete(
        `/api/v1/papers/${paper.id}?confirm=true`,
        { headers },
      );
      expect(deleted.ok()).toBe(true);
    }
    execFileSync(process.env.PAPERFLOW_PYTHON || "python3", [
      "-c",
      `
import sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]) / "paperflow.sqlite3") as db:
    db.execute("DELETE FROM discovery_papers WHERE id=?", (sys.argv[2],))
`,
      storage.data_dir,
      candidateId,
    ]);
    const {
      api_key_configured: _configured,
      api_key_source: _source,
      ...preferences
    } = initial;
    void _configured;
    void _source;
    await request.patch("/api/v1/discovery/settings", {
      headers,
      data: preferences,
    });
    await request.patch("/api/v1/settings", {
      headers,
      data: { theme: storage.theme },
    });
  }
});

test("Research Discovery settings persist and the API Key never returns", async ({
  page,
  request,
  baseURL,
}) => {
  const initial = await (
    await request.get("/api/v1/discovery/settings")
  ).json();
  const headers = { "X-PaperFlow": "1", Origin: baseURL! };
  try {
    await page.goto("/settings#research-discovery");
    await expect(
      page.getByRole("heading", { name: "Research Discovery", exact: true }),
    ).toBeVisible();
    await page
      .getByLabel("整体研究兴趣", { exact: true })
      .fill("集成测试：关注无人机在动态环境中的主动视觉。");
    await page.getByLabel("更新间隔（小时）", { exact: true }).fill("72");
    await page
      .getByRole("button", { name: "新增研究方向", exact: true })
      .click();
    const direction = page.locator(".discovery-interest").last();
    await direction
      .getByLabel("方向名称", { exact: true })
      .fill("集成测试研究方向");
    await direction
      .getByLabel("关键词（逗号或换行分隔）", { exact: true })
      .fill("active perception，visual tracking\nrobotics");
    await direction.getByLabel("优先级", { exact: true }).selectOption("3");
    await page
      .getByRole("button", { name: "保存 Discovery 设置", exact: true })
      .click();
    await expect(
      page.getByRole("status").filter({ hasText: "设置已保存" }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByLabel("更新间隔（小时）", { exact: true }),
    ).toHaveValue("72");
    await expect(page.getByLabel("整体研究兴趣", { exact: true })).toHaveValue(
      "集成测试：关注无人机在动态环境中的主动视觉。",
    );
    await expect(
      page
        .locator(".discovery-interest")
        .last()
        .getByLabel("方向名称", { exact: true }),
    ).toHaveValue("集成测试研究方向");
    await page
      .getByLabel("API Key", { exact: true })
      .fill("sk-discovery-test-only-no-paid-calls");
    await page
      .getByRole("button", { name: "保存 API Key", exact: true })
      .click();
    await expect(page.getByLabel("替换 API Key", { exact: true })).toHaveValue(
      "",
    );
    const returned = await (
      await request.get("/api/v1/discovery/settings")
    ).json();
    expect(returned.api_key_configured).toBe(true);
    expect(JSON.stringify(returned)).not.toContain("sk-discovery-test-only");
    expect(
      await page.evaluate(() => JSON.stringify(localStorage)),
    ).not.toContain("sk-discovery-test-only");
    await page
      .getByRole("button", { name: "删除本机密钥", exact: true })
      .click();
    await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
    await page.goto("/discover");
    await page.getByRole("button", { name: "检查新论文", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText(/关闭|离线|在线/);
    await page.getByRole("link", { name: "All papers", exact: true }).click();
    await expect(page.getByRole("heading", { name: /Library/ })).toBeVisible();
  } finally {
    await request.post("/api/v1/discovery/api-key", {
      headers,
      data: { api_key: "" },
    });
    const {
      api_key_configured: _configured,
      api_key_source: _source,
      ...preferences
    } = initial;
    void _configured;
    void _source;
    await request.patch("/api/v1/discovery/settings", {
      headers,
      data: preferences,
    });
  }
});
