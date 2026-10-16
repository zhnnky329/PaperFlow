import { test, expect } from "../../frontend/node_modules/@playwright/test";
import { mkdir, readFile, readdir, rename, access } from "node:fs/promises";
import path from "node:path";

test("nested folders → exact classification → parent rename → app/Finder moves → subtree deletion", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const origin = new URL(page.url()).origin;
  const headers = { Origin: origin, "X-PaperFlow": "1" };
  const nav = page.getByRole("navigation", { name: "论文库导航" });
  const settings = await (await request.get("/api/v1/settings")).json();
  expect(settings.data_dir).toContain("paperflow-e2e-");
  await request.patch("/api/v1/settings", {
    headers,
    data: { theme: "light" },
  });
  await page.reload();

  async function createFolder(name: string, parentId = "") {
    if (parentId) {
      await page
        .getByRole("button", { name: "新建子文件夹", exact: true })
        .click();
    } else {
      await nav
        .getByRole("button", { name: "新建文件夹", exact: true })
        .click();
    }
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("上级文件夹", { exact: true })).toHaveValue(
      parentId,
    );
    await dialog.getByLabel("名称", { exact: true }).fill(name);
    await dialog.getByRole("button", { name: "保存", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.locator(".workspace-heading h1")).toContainText(name);
    const id = new URL(page.url()).searchParams.get("folder");
    expect(id).toMatch(/^[a-f0-9-]{36}$/);
    return id!;
  }

  const rootName = "多层文件夹验证";
  const root = await createFolder(rootName);
  const child = await createFolder("SLAM", root);
  const leaf = await createFolder("准备精读", child);
  const bytes = Buffer.concat([
    await readFile("/tmp/paperflow-e2e.pdf"),
    Buffer.from("\n% nested folder regression fixture\n"),
  ]);
  await page.getByRole("button", { name: "Add Paper", exact: true }).click();
  await expect(page.getByLabel("存入文件夹")).toHaveValue(leaf);
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByRole("button", { name: "选择 PDF 文件", exact: true }).click(),
  ]);
  await chooser.setFiles({
    name: "nested-fixture.pdf",
    mimeType: "application/pdf",
    buffer: bytes,
  });
  await expect(page.getByRole("status")).toContainText("导入成功");
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(page.locator(".paper-row")).toHaveCount(1);
  let listing = await (
    await request.get(`/api/v1/papers?collection=${leaf}`)
  ).json();
  const paperId = listing.items[0].id;
  expect(
    listing.items[0].collections.map((folder: { id: string }) => folder.id),
  ).toEqual([leaf]);
  await request.put(`/api/v1/papers/${paperId}/reading-position?mode=pdf`, {
    headers,
    data: { pdf_page: 8, pdf_scale: 1.1 },
  });

  const folderExists = (name: string) =>
    access(path.join(settings.folders_root, name)).then(
      () => true,
      () => false,
    );
  let relativePath = `${rootName}/SLAM/准备精读`;
  await expect
    .poll(() => folderExists(`${relativePath}/.paperflow.json`))
    .toBe(true);
  await nav.getByRole("link", { name: "All papers", exact: true }).click();
  await nav
    .getByRole("button", { name: `折叠文件夹 ${rootName}`, exact: true })
    .click();
  await expect(nav.locator(`a[href="/?folder=${child}"]`)).toHaveCount(0);
  await page.reload();
  await expect(
    nav.getByRole("button", { name: `展开文件夹 ${rootName}`, exact: true }),
  ).toHaveAttribute("aria-expanded", "false");
  await expect(nav.locator(`a[href="/?folder=${child}"]`)).toHaveCount(0);
  await page.goto(`/?folder=${leaf}`);
  await expect(nav.locator(`a[href="/?folder=${child}"]`)).toBeVisible();
  await expect(nav.locator(`a[href="/?folder=${leaf}"]`)).toBeVisible();
  await page
    .getByRole("navigation", { name: "文件夹路径" })
    .getByRole("link", { name: rootName, exact: true })
    .click();
  await expect(page.locator(".folder-card")).toHaveCount(1);
  await expect(page.locator(".paper-row")).toHaveCount(0);
  await page.locator(".folder-card").click();
  await expect(page.locator(".folder-card")).toHaveCount(1);
  await page.locator(".folder-card").click();
  await expect(page.locator(".paper-row")).toHaveCount(1);

  await nav
    .getByRole("button", { name: `管理文件夹 ${rootName}`, exact: true })
    .click();
  const renamedRoot = `${rootName}（已改名）`;
  await page.getByLabel("名称", { exact: true }).fill(renamedRoot);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  relativePath = `${renamedRoot}/SLAM/准备精读`;
  await expect
    .poll(() => folderExists(`${relativePath}/.paperflow.json`))
    .toBe(true);
  await expect.poll(() => folderExists(rootName)).toBe(false);
  await expect(
    page.getByRole("navigation", { name: "文件夹路径" }),
  ).toContainText(renamedRoot);

  const otherRoot = await createFolder("多层移动目标");
  const otherChild = await createFolder("SLAM", otherRoot);
  await page.goto(`/?folder=${leaf}`);
  await nav
    .getByRole("button", { name: `管理文件夹 ${relativePath}`, exact: true })
    .click();
  const parentSelect = page.getByLabel("上级文件夹", { exact: true });
  await expect(parentSelect.locator(`option[value="${leaf}"]`)).toHaveCount(0);
  await parentSelect.selectOption(otherChild);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  relativePath = "多层移动目标/SLAM/准备精读";
  await expect
    .poll(() => folderExists(`${relativePath}/.paperflow.json`))
    .toBe(true);
  await expect(
    page.getByRole("navigation", { name: "文件夹路径" }),
  ).toContainText("多层移动目标");
  await expect(page.locator(".paper-row")).toHaveCount(1);

  await page
    .getByRole("button", {
      name: "整理 PaperFlow Test Research 到文件夹",
      exact: true,
    })
    .click();
  const picker = page.getByRole("dialog");
  await expect(
    picker.getByRole("checkbox", { name: `${renamedRoot}/SLAM`, exact: true }),
  ).not.toBeChecked();
  await expect(
    picker.getByRole("checkbox", {
      name: "多层移动目标/SLAM/准备精读",
      exact: true,
    }),
  ).toBeChecked();
  await picker.getByRole("button", { name: "关闭", exact: true }).click();

  await rename(
    path.join(settings.folders_root, relativePath),
    path.join(settings.folders_root, renamedRoot, "SLAM", "准备精读"),
  );
  relativePath = `${renamedRoot}/SLAM/准备精读`;
  await expect
    .poll(async () => {
      const paper = await (
        await request.get(`/api/v1/papers/${paperId}`)
      ).json();
      return paper.collections[0]?.path;
    })
    .toBe(relativePath);
  await expect(
    page.getByRole("navigation", { name: "文件夹路径" }),
  ).toContainText(renamedRoot);
  await mkdir(
    path.join(settings.folders_root, relativePath, "Finder 子文件夹"),
  );
  await expect(page.locator(".folder-card")).toContainText("Finder 子文件夹", {
    timeout: 15000,
  });
  const files = await readdir(path.join(settings.folders_root, relativePath));
  expect(files.filter((name) => name.endsWith(".pdf"))).toHaveLength(1);

  await mkdir("../docs/validation/nested-folders", { recursive: true });
  for (const theme of ["light", "dark"]) {
    await request.patch("/api/v1/settings", { headers, data: { theme } });
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    for (const width of [1280, 900, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(page.locator(".sidebar")).toHaveCount(1);
      await expect
        .poll(() =>
          page.evaluate(
            () => document.documentElement.scrollWidth - innerWidth,
          ),
        )
        .toBeLessThanOrEqual(1);
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
      await page.screenshot({
        path: `../docs/validation/nested-folders/${theme}-${width}.png`,
      });
    }
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await nav
    .getByRole("button", { name: `管理文件夹 ${renamedRoot}`, exact: true })
    .click();
  await page
    .getByRole("button", { name: "删除文件夹（保留论文）", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("子文件夹");
  await page
    .getByRole("button", { name: "确认删除文件夹（保留论文）", exact: true })
    .click();
  await expect
    .poll(async () => {
      const folders = await (await request.get("/api/v1/collections")).json();
      return folders.some((folder: { id: string }) =>
        [root, child, leaf].includes(folder.id),
      );
    })
    .toBe(false);
  listing = await (await request.get(`/api/v1/papers/${paperId}`)).json();
  expect(listing.collections).toEqual([]);
  expect((await request.get(`/api/v1/papers/${paperId}/pdf`)).ok()).toBe(true);
  const progress = await (
    await request.get(`/api/v1/papers/${paperId}/reading-position?mode=pdf`)
  ).json();
  expect(progress.pdf_page).toBe(8);
  await request.delete(`/api/v1/collections/${otherRoot}`, { headers });
});
