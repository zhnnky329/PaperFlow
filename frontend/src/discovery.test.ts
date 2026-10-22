import { describe, expect, it } from "vitest";
import {
  discoveryBasis,
  discoveryDate,
  discoveryQuery,
  splitDiscoveryKeywords,
} from "./discovery";

describe("discovery filters and evidence", () => {
  it("preserves an explicit zero score and sends the selected direction and view", () => {
    const params = new URLSearchParams(
      discoveryQuery({
        view: "history",
        sort: "recent",
        interest: "navigation",
        minScore: "0",
        page: 2,
      }),
    );
    expect(Object.fromEntries(params)).toEqual({
      view: "history",
      sort: "recent",
      interest_id: "navigation",
      min_score: "0",
      page: "2",
      page_size: "20",
    });
  });
  it("leaves the default threshold to the server instead of overriding it", () => {
    const params = new URLSearchParams(
      discoveryQuery({
        view: "recommended",
        sort: "score",
        interest: "",
        minScore: "",
        page: 1,
      }),
    );
    expect(params.has("min_score")).toBe(false);
    expect(params.has("interest_id")).toBe(false);
  });
  it("makes abstract fallback explicit and distinguishes partial text", () => {
    expect(discoveryBasis("abstract")).toBe("仅基于摘要判断");
    expect(discoveryBasis("partial_text")).toBe("基于部分正文");
    expect(discoveryBasis("full_text")).toBe("基于全文");
  });
  it("accepts natural keyword editing with Chinese commas and newlines", () => {
    expect(
      splitDiscoveryKeywords(
        " Visual SLAM，NeRF\nVisual SLAM, \n3D perception ",
      ),
    ).toEqual(["Visual SLAM", "NeRF", "3D perception"]);
  });
  it("handles absent and malformed timestamps without fabricating dates", () => {
    expect(discoveryDate(null)).toBe("尚未检查");
    expect(discoveryDate("invalid")).toBe("时间未知");
  });
});
