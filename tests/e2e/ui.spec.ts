import {
  test,
  expect,
  type Page,
  type Locator,
} from "../../frontend/node_modules/@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import type { Label, Paper, Settings, Position } from "../../frontend/src/api";

const widths = [1280, 900, 390];
const themes = ["light", "dark"] as const;
const paperIds = [
  "011b02c3-9b74-4f6b-908d-000000000001",
  "011b02c3-9b74-4f6b-908d-000000000002",
  "011b02c3-9b74-4f6b-908d-000000000003",
];
const folders: Label[] = [
  { id: "visual-slam", name: "SLAM 与机器人定位", paper_count: 2 },
  {
    id: "visual-planning",
    name: "Motion planning and autonomous navigation",
    paper_count: 1,
  },
];
const tag: Label = { id: "visual-tag", name: "robotics" };

function fixturePaper(overrides: Partial<Paper>): Paper {
  return {
    id: paperIds[0],
    title: "PaperFlow visual test fixture",
    authors: ["Automated Fixture"],
    year: 2025,
    abstract: "Generated test data used only by the visual regression suite.",
    source_url: null,
    arxiv_id: null,
    arxiv_version: 1,
    official_html_url: null,
    has_pdf: true,
    has_html: false,
    read_status: "unread",
    metadata_status: "succeeded",
    doi: null,
    venue: null,
    venue_kind: null,
    affiliations: [],
    metadata_sources: {},
    metadata_candidates: [],
    metadata_error: null,
    publication_sources: [],
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    last_read_at: null,
    tags: [tag],
    collections: [folders[0]],
    conversion: null,
    ...overrides,
  };
}

// Route fixtures exercise the real React surfaces without changing the isolated
// library shared by library.spec.ts. That suite covers the live API workflows.
async function installFixtures(page: Page, theme: Settings["theme"]) {
  let config: Settings = {
    theme,
    font_scale: 17,
    reader_width: 780,
    marker_mode: "fast",
    auto_convert_on_import: false,
    marker_available: false,
    marker_device: "cpu",
    marker_backend: "llamacpp",
    llama_available: false,
    folder_open_available: false,
    data_dir: "/tmp/paperflow-e2e-visual/paperflow",
    folders_root: "/tmp/paperflow-e2e-visual/paperflow/folders",
    folder_sync: { status: "succeeded", error: null },
  };
  let position: Position = {
    pdf_page: 1,
    pdf_scale: 1,
    html_anchor: "",
    scroll_ratio: 0,
  };
  let papers = [
    fixturePaper({
      id: paperIds[0],
      title: "FAST-LIO2: Fast Direct LiDAR-inertial Odometry",
      authors: ["Wei Xu", "Yixi Cai", "Dongjiao He", "Jiarong Lin"],
      year: 2022,
      read_status: "reading",
      doi: "10.1109/TRO.2022.3141876",
      venue: "IEEE Transactions on Robotics",
      venue_kind: "journal",
      arxiv_id: "2107.06829",
      affiliations: [{ name: "Test Research University", authors: ["Wei Xu"] }],
      publication_sources: [
        {
          kind: "journal",
          label: "IEEE Transactions on Robotics",
          url: "https://doi.org/10.1109/TRO.2022.3141876",
        },
        {
          kind: "arxiv",
          label: "arXiv:2107.06829",
          url: "https://arxiv.org/abs/2107.06829",
        },
      ],
    }),
    fixturePaper({
      id: paperIds[1],
      title:
        "面向复杂环境的自主导航：视觉、语言与运动规划的联合建模及跨场景鲁棒性评估",
      authors: ["视觉回归测试作者", "Visual Regression Fixture"],
      read_status: "finished",
      collections: [folders[1]],
      metadata_status: "needs_review",
      has_html: true,
      conversion: {
        id: "visual-job",
        status: "failed",
        progress_stage: "converting",
        error_message: "测试转换失败状态：PDF 原文仍可阅读。",
        attempt: 1,
      },
    }),
    fixturePaper({
      id: paperIds[2],
      title: "Visual regression fixture: a short title",
      authors: [],
      year: null,
      tags: [],
      collections: [],
    }),
  ];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const endpoint = url.pathname.replace("/api/v1", "");
    if (endpoint === "/settings") {
      if (request.method() === "PATCH")
        config = { ...config, ...request.postDataJSON() };
      await route.fulfill({ json: config });
    } else if (endpoint === "/collections") {
      await route.fulfill({ json: folders });
    } else if (endpoint === "/tags") {
      await route.fulfill({ json: [tag] });
    } else if (endpoint === "/papers") {
      const query = (url.searchParams.get("q") || "").toLowerCase();
      let items = papers.filter((paper) =>
        `${paper.title} ${paper.authors.join(" ")} ${paper.tags.map((label) => label.name).join(" ")}`
          .toLowerCase()
          .includes(query),
      );
      const status = url.searchParams.get("status");
      const collection = url.searchParams.get("collection");
      if (status) items = items.filter((paper) => paper.read_status === status);
      if (collection)
        items = items.filter((paper) =>
          paper.collections.some((label) => label.id === collection),
        );
      if (url.searchParams.get("unfiled"))
        items = items.filter((paper) => paper.collections.length === 0);
      if (url.searchParams.get("tag"))
        items = items.filter((paper) => paper.tags.length > 0);
      await route.fulfill({ json: { items, total: items.length } });
    } else if (endpoint.endsWith("/reading-position")) {
      if (request.method() === "PUT")
        position = { ...position, ...request.postDataJSON() };
      await route.fulfill({ json: position });
    } else if (endpoint.endsWith("/pdf")) {
      await route.fulfill({
        contentType: "application/pdf",
        body: await readFile("/tmp/paperflow-e2e.pdf"),
      });
    } else if (/^\/papers\/[^/]+$/.test(endpoint)) {
      const id = endpoint.split("/").pop();
      if (request.method() === "PATCH")
        papers = papers.map((paper) =>
          paper.id === id ? { ...paper, ...request.postDataJSON() } : paper,
        );
      await route.fulfill({ json: papers.find((paper) => paper.id === id) });
    } else {
      // Never let an unimplemented fixture accidentally operate the live library.
      await route.fulfill({
        status: 501,
        json: {
          error: { message: `Unexpected visual fixture request: ${endpoint}` },
        },
      });
    }
  });
}

async function screenshot(page: Page, name: string) {
  const directory = path.resolve("../docs/validation/ui");
  await mkdir(directory, { recursive: true });
  await page.screenshot({
    path: path.join(directory, `${name}.png`),
    fullPage: false,
  });
}

async function expectNoPageOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
    )
    .toBeLessThanOrEqual(1);
}

async function expectSingleLineButtons(scope: Locator) {
  const wrapped = await scope
    .locator("button, a.button")
    .evaluateAll((buttons) =>
      buttons.flatMap((button) => {
        if (!(button instanceof HTMLElement) || !button.getClientRects().length)
          return [];
        const tops = new Set<number>();
        const walker = document.createTreeWalker(button, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          if (!node.textContent?.trim()) continue;
          const range = document.createRange();
          range.selectNodeContents(node);
          for (const rect of range.getClientRects())
            if (rect.width > 0) tops.add(Math.round(rect.top));
        }
        return tops.size > 1
          ? [button.textContent?.trim() || button.getAttribute("aria-label")]
          : [];
      }),
    );
  expect(
    wrapped,
    "visible desktop buttons must keep their text on one line",
  ).toEqual([]);
}

async function expectColumnAlignment(page: Page) {
  for (const selector of [
    ".paper-title",
    ".paper-actions select",
    ".paper-more",
  ]) {
    const edges = await page
      .locator(`.paper-row ${selector}`)
      .evaluateAll((elements) =>
        elements.map((element) => {
          const rectangle = element.getBoundingClientRect();
          return { left: rectangle.left, right: rectangle.right };
        }),
      );
    expect(edges).toHaveLength(3);
    const key = selector === ".paper-title" ? "left" : "right";
    expect(
      Math.max(...edges.map((edge) => edge[key])) -
        Math.min(...edges.map((edge) => edge[key])),
      `${selector} column alignment`,
    ).toBeLessThanOrEqual(1);
  }
}

for (const theme of themes) {
  test(`${theme}: Library columns, navigation and search stay aligned across viewport sizes`, async ({
    page,
  }) => {
    await installFixtures(page, theme);
    await page.emulateMedia({ reducedMotion: "reduce", colorScheme: theme });
    await page.goto("/");
    await expect(page.locator(".paper-row")).toHaveCount(3);
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await expect(
        page.getByRole("navigation", { name: "论文库导航" }),
      ).toBeVisible();
      await expect(
        page.getByRole("link", { name: "Settings", exact: true }),
      ).toBeVisible();
      await expectNoPageOverflow(page);
      if (width >= 900) {
        await expectColumnAlignment(page);
        await expectSingleLineButtons(page.locator(".workspace"));
      }
      await screenshot(page, `library-${theme}-${width}`);
      const search = page.getByLabel("搜索论文");
      await search.fill("no-such-visual-fixture");
      await expect(
        page.getByRole("heading", { name: "没有匹配的论文" }),
      ).toBeVisible();
      await expectNoPageOverflow(page);
      await page.getByRole("button", { name: "清除筛选", exact: true }).click();
      await expect(page.locator(".paper-row")).toHaveCount(3);
    }
    // A real keyboard focus, rather than pointer focus, must draw a visible ring.
    const search = page.getByLabel("搜索论文");
    await search.blur();
    await page.keyboard.press("/");
    await expect(search).toBeFocused();
    const outline = await page.locator(".search-box").evaluate((node) => ({
      width: getComputedStyle(node).outlineWidth,
      style: getComputedStyle(node).outlineStyle,
    }));
    expect(parseFloat(outline.width)).toBeGreaterThanOrEqual(2);
    expect(outline.style).not.toBe("none");
    const reduced = await page
      .locator(".button")
      .first()
      .evaluate((node) => ({
        animation: getComputedStyle(node).animationDuration,
        transition: getComputedStyle(node).transitionDuration,
      }));
    expect(reduced.animation).toBe("0s");
    expect(reduced.transition).toBe("0s");
  });

  test(`${theme}: import, paper details and folder picker remain usable on desktop and narrow screens`, async ({
    page,
  }) => {
    await installFixtures(page, theme);
    await page.goto("/");
    await expect(page.locator(".paper-row")).toHaveCount(3);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page
        .getByRole("button", { name: "Add Paper", exact: true })
        .click();
      const dialog = page.getByRole("dialog");
      await dialog
        .getByRole("button", { name: "PDF File", exact: true })
        .click();
      await expect(dialog.getByLabel("存入文件夹")).toBeVisible();
      await expect(
        dialog.getByRole("button", { name: "选择 PDF 文件", exact: true }),
      ).toBeVisible();
      await expectNoPageOverflow(page);
      if (width >= 900) await expectSingleLineButtons(dialog);
      await screenshot(page, `import-${theme}-${width}`);
      await dialog
        .getByRole("button", { name: "arXiv Link", exact: true })
        .click();
      await expect(
        dialog.getByLabel("arXiv URL / ID", { exact: true }),
      ).toBeVisible();
      await dialog.getByRole("button", { name: "关闭", exact: true }).click();
      await page
        .getByRole("button", {
          name: "编辑 FAST-LIO2: Fast Direct LiDAR-inertial Odometry",
          exact: true,
        })
        .click();
      await expect(dialog.getByLabel("标题", { exact: true })).toHaveValue(
        "FAST-LIO2: Fast Direct LiDAR-inertial Odometry",
      );
      await expectNoPageOverflow(page);
      await screenshot(page, `details-${theme}-${width}`);
      await dialog.getByRole("button", { name: "关闭", exact: true }).click();
      await page
        .getByRole("button", {
          name: "整理 FAST-LIO2: Fast Direct LiDAR-inertial Odometry 到文件夹",
          exact: true,
        })
        .click();
      await expect(
        dialog.getByRole("checkbox", { name: folders[0].name, exact: true }),
      ).toBeChecked();
      await expect(
        dialog.getByRole("checkbox", { name: folders[1].name, exact: true }),
      ).toBeVisible();
      await expectNoPageOverflow(page);
      await screenshot(page, `folders-${theme}-${width}`);
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
    }
  });

  test(`${theme}: Settings fields and long storage paths fit every target viewport`, async ({
    page,
  }) => {
    await installFixtures(page, theme);
    await page.goto("/settings");
    await expect(page.getByLabel("主题", { exact: true })).toHaveValue(theme);
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await expectNoPageOverflow(page);
      await expect(page.getByLabel("主题", { exact: true })).toBeVisible();
      await expect(page.getByLabel("正文宽度")).toBeVisible();
      if (width >= 900)
        await expectSingleLineButtons(page.locator(".workspace"));
      await screenshot(page, `settings-${theme}-${width}`);
    }
  });

  test(`${theme}: PDF.js renders and keeps reading controls within the viewport`, async ({
    page,
  }) => {
    await installFixtures(page, theme);
    await page.goto(`/papers/${paperIds[0]}/pdf`);
    await expect(page.getByLabel("页码", { exact: true })).toBeEnabled();
    await expect(page.locator(".textLayer").first()).toContainText(
      "PaperFlow test document",
    );
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await expectNoPageOverflow(page);
      await expect(
        page.getByRole("link", { name: "返回 Library", exact: true }),
      ).toBeVisible();
      const controls = page.locator(".reader-controls");
      const rectangle = await controls.boundingBox();
      expect(rectangle).not.toBeNull();
      expect(rectangle!.x).toBeGreaterThanOrEqual(0);
      expect(rectangle!.x + rectangle!.width).toBeLessThanOrEqual(width + 1);
      if (width >= 900)
        await expectSingleLineButtons(page.locator(".reader-toolbar"));
      await page.getByRole("button", { name: "适配宽度", exact: true }).click();
      await expect(page.locator(".pdf-page").first()).toHaveJSProperty(
        "offsetWidth",
        width - 80,
      );
      await expect(page.locator(".textLayer").first()).toContainText(
        "PaperFlow test document",
      );
      await screenshot(page, `pdf-${theme}-${width}`);
    }
    await page.getByLabel("页码", { exact: true }).fill("2");
    await expect(page.getByLabel("页码", { exact: true })).toHaveValue("2");
    await page.getByRole("button", { name: "放大", exact: true }).click();
    await expectNoPageOverflow(page);
  });
}
