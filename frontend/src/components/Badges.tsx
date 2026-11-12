// Text-first badges (DESIGN.md): colour is never the only signal, unknown is never green.
import { ANALYSIS_LABELS, MODEL_STATE_LABELS, TIER_LABELS } from "../lib/format";
import type { AnalysisStatus, ModelState, Tier } from "../lib/api/types";

export function RiskBadge({ tier }: { tier: Tier }) {
  return (
    <span className={`badge badge-tier-${tier}`}>
      Risk tier: {TIER_LABELS[tier]}
      {tier === "unknown" ? " (no calibrated signal)" : null}
    </span>
  );
}

export function StatusBadge({ status }: { status: AnalysisStatus }) {
  return (
    <span className={`badge badge-status-${status}`}>Analysis: {ANALYSIS_LABELS[status]}</span>
  );
}

export function ModelStateBadge({ state }: { state: ModelState }) {
  return <span className={`badge badge-model-${state}`}>{MODEL_STATE_LABELS[state]}</span>;
}
