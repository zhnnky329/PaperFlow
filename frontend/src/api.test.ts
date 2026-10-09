import { describe, it, expect, vi, afterEach } from "vitest";
import { api, preferredLink, type Paper } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("typed API boundary", () => {
  it("adds CSRF marker to mutations and preserves upload form", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetch);
    await api("/settings", {
      method: "PATCH",
      body: JSON.stringify({ theme: "dark" }),
    });
    const options = fetch.mock.calls[0][1];
    expect(options.headers.get("X-PaperFlow")).toBe("1");
    expect(options.headers.get("Content-Type")).toBe("application/json");
  });
  it("propagates actionable API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          status: 503,
          json: async () => ({ error: { message: "Marker missing" } }),
        }),
    );
    await expect(api("/health")).rejects.toThrow("Marker missing");
  });
  it("uses only verified official URLs before local HTML/PDF", () => {
    const p = { id: "id", has_html: true, official_html_url: null } as Paper;
    expect(preferredLink(p)).toBe("/read/id/html");
    p.has_html = false;
    expect(preferredLink(p)).toBe("/papers/id/pdf");
    p.official_html_url = "https://arxiv.org/html/2402.08954";
    expect(preferredLink(p)).toBe(p.official_html_url);
  });
});
