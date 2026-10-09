import { test, expect } from "../../frontend/node_modules/@playwright/test";

test("real Library → upload → edit → PDF.js → progress → delete", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("你的下一篇论文，从这里开始")).toBeVisible();
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
  await page.getByLabel("Collections（逗号分隔）").fill("Planning");
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
