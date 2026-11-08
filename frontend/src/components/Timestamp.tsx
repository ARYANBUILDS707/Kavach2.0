import { formatTimestamp } from "../lib/format";

/** Local time with its zone; the exact UTC value is in the machine-readable attribute and
 * available to assistive technology (DESIGN.md). */
export function Timestamp({ iso }: { iso: string }) {
  const { local, utc } = formatTimestamp(iso);
  return (
    <time dateTime={utc} title={`UTC ${utc}`}>
      {local}
      <span className="visually-hidden"> (UTC {utc})</span>
    </time>
  );
}
