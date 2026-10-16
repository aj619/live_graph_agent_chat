import { describe, expect, it } from "vitest";
import { checkUpload } from "../src/limits";
import type { ConfigResponse } from "../src/types";

const config: ConfigResponse = {
  max_documents: 2,
  max_file_size_mb: 1,
  allowed_extensions: ["pdf", "txt"],
};

describe("checkUpload", () => {
  it("accepts a file within every limit", () => {
    expect(checkUpload({ name: "a.pdf", size: 100 }, config, 0)).toEqual({ ok: true });
  });

  it("rejects when the document count is already at the max", () => {
    expect(checkUpload({ name: "a.pdf", size: 100 }, config, 2)).toEqual({
      ok: false,
      reason: "too-many-documents",
    });
  });

  it("rejects a disallowed extension", () => {
    expect(checkUpload({ name: "a.exe", size: 100 }, config, 0)).toEqual({
      ok: false,
      reason: "disallowed-extension",
    });
  });

  it("rejects a file with no extension", () => {
    expect(checkUpload({ name: "a", size: 100 }, config, 0)).toEqual({
      ok: false,
      reason: "disallowed-extension",
    });
  });

  it("rejects a file over the max size", () => {
    const oversize = config.max_file_size_mb * 1024 * 1024 + 1;
    expect(checkUpload({ name: "a.pdf", size: oversize }, config, 0)).toEqual({
      ok: false,
      reason: "too-large",
    });
  });

  it("accepts a file exactly at the max size", () => {
    const exact = config.max_file_size_mb * 1024 * 1024;
    expect(checkUpload({ name: "a.pdf", size: exact }, config, 0)).toEqual({ ok: true });
  });
});
