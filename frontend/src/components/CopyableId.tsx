import { useState } from "react";

/** A monospace identifier (incident or request ID) with a copy action. */
export function CopyableId({ label, value }: { label?: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span>
      {label !== undefined ? `${label}: ` : null}
      <span className="copyable-id">{value}</span>{" "}
      <button
        type="button"
        className="button button-secondary"
        onClick={() => {
          void navigator.clipboard.writeText(value).then(
            () => {
              setCopied(true);
            },
            () => {
              setCopied(false);
            },
          );
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}
