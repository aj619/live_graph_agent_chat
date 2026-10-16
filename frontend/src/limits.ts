/** Client-side upload pre-check mirroring the server limits (plan §6.3, §7.1). The server stays authoritative. */

import type { ConfigResponse } from "./types";

export type UploadRejectionReason = "too-many-documents" | "disallowed-extension" | "too-large";

export interface UploadCheckResult {
  ok: boolean;
  reason?: UploadRejectionReason;
}

export function checkUpload(
  file: { name: string; size: number },
  config: ConfigResponse,
  currentDocumentCount: number,
): UploadCheckResult {
  if (currentDocumentCount >= config.max_documents) {
    return { ok: false, reason: "too-many-documents" };
  }

  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  const allowed = config.allowed_extensions.map((entry) => entry.toLowerCase());
  if (!extension || !allowed.includes(extension)) {
    return { ok: false, reason: "disallowed-extension" };
  }

  const maxBytes = config.max_file_size_mb * 1024 * 1024;
  if (file.size > maxBytes) {
    return { ok: false, reason: "too-large" };
  }

  return { ok: true };
}

export function rejectionMessage(reason: UploadRejectionReason): string {
  switch (reason) {
    case "too-many-documents":
      return "The maximum number of documents has been reached.";
    case "disallowed-extension":
      return "This file type is not allowed.";
    case "too-large":
      return "The file is larger than the allowed size.";
  }
}
