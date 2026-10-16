/** Left column: upload button and document table with status and progress (plan §7.1). */

import { useRef, type ChangeEvent } from "react";
import type { ConfigResponse, Document } from "../types";

interface FileListProps {
  documents: Document[];
  config: ConfigResponse | null;
  uploadError: string | null;
  onUpload: (file: File) => void;
  onDelete: (id: string) => void;
}

function statusLabel(doc: Document): string {
  if (doc.status === "processing") {
    const total = doc.chunks_total;
    return total ? `processing (${doc.chunks_done}/${total})` : "processing";
  }
  return doc.status;
}

export function FileList({ documents, config, uploadError, onUpload, onDelete }: FileListProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const accept = config ? config.allowed_extensions.map((ext) => `.${ext}`).join(",") : undefined;

  function handleChange(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) onUpload(file);
  }

  return (
    <section className="panel file-list" aria-label="Documents">
      <h2>Documents</h2>
      <div className="file-list__upload">
        <button type="button" onClick={() => inputRef.current?.click()} disabled={!config}>
          Upload document
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          onChange={handleChange}
          hidden
          data-testid="file-input"
        />
      </div>
      {uploadError && <p className="file-list__error">{uploadError}</p>}
      <table className="file-list__table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th aria-label="Delete" />
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr key={doc.id}>
              <td className="file-list__name" title={doc.filename}>
                {doc.filename}
              </td>
              <td>
                <span className={`status-badge status-badge--${doc.status}`}>
                  {statusLabel(doc)}
                </span>
                {doc.error && <p className="file-list__doc-error">{doc.error}</p>}
              </td>
              <td>
                <button type="button" onClick={() => onDelete(doc.id)} aria-label={`Delete ${doc.filename}`}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {documents.length === 0 && (
            <tr>
              <td colSpan={3} className="file-list__empty">
                No documents yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
