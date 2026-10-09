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
  await page.getByLabel("Tags（逗号分隔）").fill("robotics");
  await page.getByRole("button", { name: "保存更改" }).click();
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
