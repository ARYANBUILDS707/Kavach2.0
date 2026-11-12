// System status (DESIGN.md "System"): the SMS model's operational state from
// GET /system/models, shared with the header via ModelStatusProvider (no extra polling).
import { useModelStatus } from "../../app/ModelStatusProvider";
import { ModelStateBadge } from "../../components/Badges";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { LOADING, StateView, describeError } from "../../components/StateView";
import { NOT_AVAILABLE, formatClockTime, reasonLabel } from "../../lib/format";
import type { ModelState } from "../../lib/api/types";

const STATE_EXPLANATIONS: Record<ModelState, string> = {
  ready:
    "The pinned model loaded and passed its self-test. Ready describes operation only; it says nothing about accuracy.",
  starting: "The model worker is starting. SMS submissions are refused until it is ready.",
  disabled:
    "The SMS model is not enabled on this deployment. Incidents are stored with the analysis stage unavailable.",
  unavailable:
    "The model worker cannot serve requests. Incidents are stored with the analysis stage unavailable and a reason.",
};

export function SystemPage() {
  const { status, error, loading, checkedAt, refresh } = useModelStatus();

  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="System status"
        lead="Operational readiness of the SMS model. Ready describes whether it can run, never how accurate it is."
      />
      <div className="system-grid">
        <section className="card" aria-labelledby="sms-model-heading">
          <p className="eyebrow">Model worker</p>
          <h2 id="sms-model-heading">SMS model</h2>
          {status === null ? (
            loading ? (
              <StateView state={LOADING} />
            ) : (
              <StateView
                state={describeError(error)}
                action={<Button onClick={refresh}>Check again</Button>}
              />
            )
          ) : (
            <>
              {error !== null ? (
                <Banner tone="error">
                  The latest check failed; showing the status from{" "}
                  {checkedAt !== null ? formatClockTime(checkedAt) : "an earlier check"}.
                </Banner>
              ) : null}
              <p className="system-state">
                <ModelStateBadge state={status.state} />
              </p>
              <p>{STATE_EXPLANATIONS[status.state]}</p>
              <dl className="facts">
                <dt>Supervisor state</dt>
                <dd className="copyable-id">{status.detail}</dd>
                <dt>Last failure or refusal</dt>
                <dd>
                  {status.reason === null ? (
                    "None reported"
                  ) : (
                    <>
                      {reasonLabel(status.reason)}{" "}
                      <span className="shell-meta">({status.reason})</span>
                    </>
                  )}
                </dd>
                <dt>Model version</dt>
                <dd className="copyable-id">{status.model_version ?? NOT_AVAILABLE}</dd>
                <dt>Score semantics</dt>
                <dd>Uncalibrated softmax: native scores, not probabilities</dd>
                <dt>Validated on KAVACH data</dt>
                {/* The contract fixes this to false until a validated calibration exists. */}
                <dd>No: not validated on KAVACH data</dd>
                <dt>Last checked</dt>
                <dd>{checkedAt !== null ? formatClockTime(checkedAt) : NOT_AVAILABLE}</dd>
              </dl>
              <Button variant="secondary" onClick={refresh}>
                Check again
              </Button>
            </>
          )}
        </section>
        <section className="card" aria-labelledby="limits-heading">
          <p className="eyebrow">Ground rules</p>
          <h2 id="limits-heading">Data handling and limitations</h2>
          <ul className="limits-list">
            <li>Message text is never retained or shown; incidents keep only analysis evidence.</li>
            <li>Evidence expires after 7 days.</li>
            <li>Risk tiers stay unknown and scores stay empty until a calibration validated on KAVACH data exists.</li>
            <li>Correlation between SMS and calls is not part of this release.</li>
          </ul>
        </section>
      </div>
    </>
  );
}
