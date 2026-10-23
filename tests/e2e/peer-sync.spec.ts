import { test, expect } from "../../frontend/node_modules/@playwright/test";
import { readFile } from "node:fs/promises";

test("local conversion stays available alongside Ubuntu in Library and PDF reader", async ({ page, request, baseURL }) => {
  const headers = { Origin: baseURL!, "X-PaperFlow": "1" };
  const bytes = Buffer.concat([await readFile("/tmp/paperflow-e2e.pdf"), Buffer.from(`\n% peer-ui-${Date.now()}\n`)]);
  const uploaded = await request.post("/api/v1/papers/upload", {
    headers, multipart: { file: { name: "peer-ui.pdf", mimeType: "application/pdf", buffer: bytes } },
  });
  expect(uploaded.ok()).toBeTruthy();
  const { paper } = await uploaded.json();
  await request.patch(`/api/v1/papers/${paper.id}`, { headers, data: { title: "Peer conversion controls" } });
  await page.route("**/api/v1/settings", async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), remote_conversion_available: true } });
  });
  const targets: (string | undefined)[] = [];
  await page.route(`**/api/v1/papers/${paper.id}/conversions`, async route => {
    targets.push(route.request().postDataJSON().target);
    await route.fulfill({ json: { job: { id: "ui-only", status: "queued", progress_stage: "waiting", attempt: 1 }, cached: false } });
  });
  try {
    await page.goto("/");
    const row = page.locator(".paper-row").filter({ hasText: "Peer conversion controls" });
    await row.getByRole("button", { name: "Convert", exact: true }).click();
    await expect.poll(() => targets.length).toBe(1);
    expect(targets[0]).toBeUndefined();
    await row.getByRole("button", { name: "使用 Ubuntu 转换", exact: true }).click();
    await expect.poll(() => targets.length).toBe(2);
    expect(targets[1]).toBe("ubuntu");
    await page.goto(`/papers/${paper.id}/pdf`);
    await expect(page.getByLabel("页码")).toBeEnabled();
    await page.getByRole("button", { name: "Convert HTML", exact: true }).click();
    await expect.poll(() => targets.length).toBe(3);
    expect(targets[2]).toBe("local");
    await page.getByRole("button", { name: "使用 Ubuntu 转换", exact: true }).click();
    await expect.poll(() => targets.length).toBe(4);
    expect(targets[3]).toBe("ubuntu");
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "双机同步", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "立即同步", exact: true })).toBeDisabled();
  } finally {
    await request.delete(`/api/v1/papers/${paper.id}?confirm=true`, { headers });
  }
});
