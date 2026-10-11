import { test, expect } from "../../frontend/node_modules/@playwright/test";

test("real Library → upload → edit → PDF.js → progress → delete", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("你的下一篇论文，从这里开始")).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "新建文件夹", exact: true })
    .click();
  await page.getByLabel("名称", { exact: true }).fill("Planning");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Planning", exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add Paper", exact: true }).click();
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByRole("button", { name: "选择 PDF 文件", exact: true }).click(),
  ]);
  await chooser.setFiles("/tmp/paperflow-e2e.pdf");
  await expect(page.getByRole("status")).toContainText("导入成功");
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(
    page.getByText("PaperFlow Test Research", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "编辑 PaperFlow Test Research" })
    .click();
  await page.getByLabel("标题", { exact: true }).fill("SLAM Reading");
  await page.getByLabel("会议／期刊", { exact: true }).fill("Robotics Journal");
  await page.getByLabel("发表类型", { exact: true }).selectOption("journal");
  await page
    .getByLabel("单位（每行一个）", { exact: true })
    .fill("Research University");
  await page.getByLabel("DOI", { exact: true }).fill("10.1234/manual-test");
  await expect(
    page.getByRole("button", { name: /查找元信息|元信息获取中/ }),
  ).toBeDisabled();
  await page.getByLabel("Tags（逗号分隔）").fill("robotics");
  await page.getByRole("button", { name: "保存更改" }).click();
  await page
    .getByRole("button", { name: "编辑 SLAM Reading", exact: true })
    .click();
  await expect(page.getByLabel("会议／期刊", { exact: true })).toHaveValue(
    "Robotics Journal",
  );
  await expect(
    page.getByLabel("单位（每行一个）", { exact: true }),
  ).toHaveValue("Research University");
  await expect(page.getByLabel("DOI", { exact: true })).toHaveValue(
    "10.1234/manual-test",
  );
  await page.screenshot({ path: "../docs/validation/metadata-details.png" });
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "SLAM Reading", exact: true }),
  ).toBeVisible();
  await page.getByLabel("搜索论文").fill("robotics");
  await expect(
    page.getByRole("link", { name: "SLAM Reading", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "PDF", exact: true }).click();
  await expect(page.getByLabel("页码")).toHaveValue("1");
  await expect(page.locator(".pdf-page canvas").first()).toHaveJSProperty(
    "width",
    595,
  );
  await expect(page.locator(".textLayer").first()).toContainText(
    "PaperFlow test document",
  );
  await page.getByLabel("页码").fill("6");
  await expect(page.getByLabel("页码")).toHaveValue("6");
  await page.getByRole("button", { name: "放大", exact: true }).click();
  await expect(page.getByText("110%", { exact: true })).toBeVisible();
  await page.waitForTimeout(1100);
  await page.reload();
  await expect(page.getByLabel("页码")).toHaveValue("6");
  await expect(page.getByLabel("页码")).toBeEnabled();
  await expect(page.getByText("110%", { exact: true })).toBeVisible();
  await expect(page.locator('[data-page="6"]')).toBeInViewport();
  await expect(page.locator('[data-page="6"] .textLayer')).toContainText(
    "Page 6",
  );
  await page.screenshot({
    path: "../docs/validation/pdf-reader.png",
    fullPage: false,
  });
  await page.getByRole("link", { name: "返回 Library" }).click();
  await page.getByRole("button", { name: "编辑 SLAM Reading" }).click();
  await page.getByRole("button", { name: "删除论文", exact: true }).click();
  await page.getByRole("button", { name: "确认删除条目和本地文件" }).click();
  await expect(page.getByText("你的下一篇论文，从这里开始")).toBeVisible();
  await page.screenshot({ path: "../docs/validation/library-empty.png" });
});

test("dark mode is persisted across reload", async ({ page }) => {
  await page.goto("/settings");
  await page.getByText("Appearance", { exact: true }).waitFor();
  await page.getByLabel("主题", { exact: true }).selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: "../docs/validation/settings-dark.png" });
});

test("folder management → classify → Finder copies → rename → unfiled", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const nav = page.getByRole("navigation");
  await nav.getByRole("button", { name: "新建文件夹", exact: true }).click();
  await page.getByLabel("名称", { exact: true }).fill("机器人研究");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("heading", { name: /机器人研究/ })).toBeVisible();
  await page.getByRole("button", { name: "Add Paper", exact: true }).click();
  const folderId = new URL(page.url()).searchParams.get("folder");
  await expect(page.getByLabel("存入文件夹")).toHaveValue(folderId!);
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByRole("button", { name: "选择 PDF 文件", exact: true }).click(),
  ]);
  await chooser.setFiles("/tmp/paperflow-e2e.pdf");
  await expect(page.getByRole("status")).toContainText("导入成功");
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(page.locator(".paper-row")).toHaveCount(1);
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/v1/settings")).json()).folder_sync
          .status,
    )
    .toBe("succeeded");
  const settings = await (await request.get("/api/v1/settings")).json();
  const fs = await import("node:fs/promises");
  const path = await import("node:path");
  let folderPath = path.join(settings.folders_root, "机器人研究");
  await expect
    .poll(
      async () =>
        (await fs.readdir(folderPath)).filter((name) => name.endsWith(".pdf"))
          .length,
    )
    .toBe(1);
  await page.reload();
  await expect(page.getByRole("heading", { name: /机器人研究/ })).toBeVisible();
  await page.screenshot({ path: "../docs/validation/ui/folder-papers.png" });
  await nav
    .getByRole("button", { name: "管理文件夹 机器人研究", exact: true })
    .click();
  await page.getByLabel("名称", { exact: true }).fill("SLAM 文献");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("heading", { name: /SLAM 文献/ })).toBeVisible();
  folderPath = path.join(settings.folders_root, "SLAM 文献");
  await expect
    .poll(async () =>
      fs
        .access(folderPath)
        .then(() => true)
        .catch(() => false),
    )
    .toBe(true);
  await page
    .getByRole("button", {
      name: "整理 PaperFlow Test Research 到文件夹",
      exact: true,
    })
    .click();
  await page
    .getByRole("checkbox", { name: "SLAM 文献", exact: true })
    .uncheck();
  await page.screenshot({ path: "../docs/validation/ui/folder-picker.png" });
  await page.getByRole("button", { name: "保存归类", exact: true }).click();
  await expect(page.locator(".paper-row")).toHaveCount(0);
  await nav.getByRole("link", { name: "未分类", exact: true }).click();
  await expect(page.locator(".paper-row")).toHaveCount(1);
  await expect
    .poll(
      async () =>
        (await fs.readdir(folderPath)).filter((name) => name.endsWith(".pdf"))
          .length,
    )
    .toBe(0);
  await nav
    .getByRole("button", { name: "管理文件夹 SLAM 文献", exact: true })
    .click();
  await page
    .getByRole("button", { name: "删除文件夹（保留论文）", exact: true })
    .click();
  await page
    .getByRole("button", { name: "确认删除文件夹（保留论文）", exact: true })
    .click();
  await expect(page.locator(".paper-row")).toHaveCount(1);
});

test("cached metadata search → candidate confirmation → persisted details", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const settings = await (await request.get("/api/v1/settings")).json();
  expect(settings.data_dir).toContain("paperflow-e2e-");
  const papers = await (await request.get("/api/v1/papers")).json();
  const paper = papers.items[0];
  const { execFileSync } = await import("node:child_process");
  // A deposited Crossref response fixture in the isolated test library's cache.
  // The real worker, API, SQLite and UI still process/confirm this candidate.
  execFileSync("../.venv/bin/python", [
    "-c",
    `
import hashlib, json, sqlite3, sys, time
from pathlib import Path
query = {"title": sys.argv[2], "author": sys.argv[3]}
key = "metadata-cache:" + hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
record = {"doi":"10.1234/confirmed", "title":sys.argv[2], "authors":[sys.argv[3]], "year":2025,
          "venue":"Robotics Conference", "venue_kind":"conference",
          "affiliations":[{"name":"Example University", "authors":[sys.argv[3]]}]}
with sqlite3.connect(Path(sys.argv[1]) / "paperflow.sqlite3") as database:
    database.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (key, json.dumps({"time":time.time(), "result":[record]})))
`,
    settings.data_dir,
    paper.title,
    paper.authors[0],
  ]);
  const started = await request.post(
    `/api/v1/papers/${paper.id}/fetch-metadata`,
    {
      headers: { Origin: new URL(page.url()).origin, "X-PaperFlow": "1" },
    },
  );
  expect(started.status()).toBe(202);
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/v1/papers/${paper.id}`)).json())
          .metadata_status,
    )
    .toBe("needs_review");
  // Add an arXiv association in this isolated fixture after the lookup, so
  // presentation coverage does not depend on an external arXiv request.
  execFileSync("../.venv/bin/python", [
    "-c",
    `
import sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]) / "paperflow.sqlite3") as database:
    database.execute("UPDATE papers SET arxiv_id=?, arxiv_version=? WHERE id=?",
                     ("2501.00001", 2, sys.argv[2]))
`,
    settings.data_dir,
    paper.id,
  ]);
  await page.goto("/");
  await expect(page.locator(".paper-row .publication-source")).toHaveText([
    "arXiv:2501.00001v2",
  ]);
  await page.getByRole("button", { name: "核对元信息", exact: true }).click();
  await expect(page.locator(".metadata-candidate")).toContainText(
    "Robotics Conference",
  );
  await page.getByRole("button", { name: "采用这条信息", exact: true }).click();
  await expect(page.locator(".paper-row .publication-source")).toHaveText([
    "会议：Robotics Conference",
    "arXiv:2501.00001v2",
  ]);
  await expect(
    page.locator(".paper-row .publication-source").first(),
  ).toHaveAttribute("href", "https://doi.org/10.1234/confirmed");
  await expect(
    page.locator(".paper-row .publication-source").last(),
  ).toHaveAttribute("href", "https://arxiv.org/abs/2501.00001v2");
  await page.reload();
  await expect(page.locator(".paper-row .publication-source")).toHaveText([
    "会议：Robotics Conference",
    "arXiv:2501.00001v2",
  ]);
  await page
    .getByRole("button", { name: `编辑 ${paper.title}`, exact: true })
    .click();
  await expect(page.getByLabel("DOI", { exact: true })).toHaveValue(
    "10.1234/confirmed",
  );
  await expect(
    page.getByLabel("单位（每行一个）", { exact: true }),
  ).toHaveValue("Example University");
  await expect(page.getByLabel("会议／期刊", { exact: true })).toHaveValue(
    "Robotics Conference",
  );
  await expect(
    page.locator(".metadata-summary .publication-source"),
  ).toHaveText(["会议：Robotics Conference", "arXiv:2501.00001v2"]);
  await page.screenshot({ path: "../docs/validation/publication-sources.png" });
  await page.getByRole("button", { name: "关闭", exact: true }).click();
});

test("Finder import → rename → move → remove classification in the live Library", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const settings = await (await request.get("/api/v1/settings")).json();
  expect(settings.data_dir).toContain("paperflow-e2e-");
  const fs = await import("node:fs/promises");
  const path = await import("node:path");
  const first = path.join(settings.folders_root, "Finder 新增");
  const second = path.join(settings.folders_root, "Finder 移动");
  await fs.mkdir(first);
  const fixture = await fs.readFile("/tmp/paperflow-e2e.pdf");
  await fs.writeFile(
    path.join(first, "paper.pdf"),
    Buffer.concat([fixture, Buffer.from("\n% Finder import fixture")]),
  );
  const nav = page.getByRole("navigation");
  await expect(nav.getByRole("link", { name: /Finder 新增/ })).toBeVisible({
    timeout: 15000,
  });
  const folders = await (await request.get("/api/v1/collections")).json();
  const folder = folders.find(
    (item: { name: string }) => item.name === "Finder 新增",
  );
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(`/api/v1/papers?collection=${folder.id}`)
          ).json()
        ).total,
    )
    .toBe(1);
  const paper = (
    await (await request.get(`/api/v1/papers?collection=${folder.id}`)).json()
  ).items[0];
  await nav.getByRole("link", { name: /Finder 新增/ }).click();
  await expect(page.locator(".paper-row")).toHaveCount(1);
  const renamed = path.join(settings.folders_root, "Finder 改名");
  await fs.rename(
    path.join(first, "paper.pdf"),
    path.join(first, "my filename.pdf"),
  );
  await fs.rename(first, renamed);
  await expect(
    page.getByRole("heading", { name: /Finder 改名/ }),
  ).toBeVisible();
  await expect(page.locator(".paper-title")).toHaveText(paper.title);
  await fs.mkdir(second);
  await fs.rename(
    path.join(renamed, "my filename.pdf"),
    path.join(second, "moved.pdf"),
  );
  await expect(page.locator(".paper-row")).toHaveCount(0);
  await nav.getByRole("link", { name: /Finder 移动/ }).click();
  await expect(page.locator(".paper-row")).toHaveCount(1);
  await page.screenshot({ path: "../docs/validation/finder-two-way.png" });
  await fs.unlink(path.join(second, "moved.pdf"));
  await expect(page.locator(".paper-row")).toHaveCount(0);
  const retained = await (
    await request.get(`/api/v1/papers/${paper.id}`)
  ).json();
  expect(retained.has_pdf).toBe(true);
  expect(retained.collections).toEqual([]);
  const original = await request.get(`/api/v1/papers/${paper.id}/pdf`);
  expect(original.status()).toBe(200);
  await fs.rm(second, { recursive: true });
  await expect(nav.getByRole("link", { name: /Finder 移动/ })).toHaveCount(0);
});
