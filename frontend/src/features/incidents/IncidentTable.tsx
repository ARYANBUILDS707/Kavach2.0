// Semantic incident table (DESIGN.md "Incident table"): explicit row links, stable server order,
// and on narrow screens each row becomes a labelled block without hiding any field.
import { Link } from "react-router";

import { RiskBadge, StatusBadge } from "../../components/Badges";
import { adminIncident } from "../../app/routes";
import { Timestamp } from "../../components/Timestamp";
import { KIND_LABELS, formatScore, shortId } from "../../lib/format";
import type { IncidentSummary } from "../../lib/api/types";

export function IncidentTable({
  items,
  caption,
  returnTo,
}: {
  items: IncidentSummary[];
  caption: string;
  /** Where the detail page's back link returns, with the list's filters. */
  returnTo: string;
}) {
  return (
    // A focusable scroll region for keyboard users; named apart from the enclosing section so
    // landmarks stay unique (axe landmark-unique).
    <div className="table-region" role="region" aria-label={`${caption}, scrollable table`} tabIndex={0}>
      <table className="incident-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Event time</th>
            <th scope="col">Incident</th>
            <th scope="col">Kind</th>
            <th scope="col">Analysis</th>
            <th scope="col">Risk tier</th>
            <th scope="col">Policy risk score</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td data-label="Event time">
                <Timestamp iso={item.occurred_at} />
              </td>
              <td data-label="Incident">
                <Link to={adminIncident(item.id)} state={{ from: returnTo }}>
                  Open incident <span className="copyable-id">{shortId(item.id)}</span>
                </Link>
              </td>
              <td data-label="Kind">{KIND_LABELS[item.kind]}</td>
              <td data-label="Analysis">
                <StatusBadge status={item.analysis_status} />
              </td>
              <td data-label="Risk tier">
                <RiskBadge tier={item.tier} />
              </td>
              <td data-label="Policy risk score">{formatScore(item.final_score)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
