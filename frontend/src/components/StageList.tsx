import { reasonLabel, stageLabel } from "../lib/format";
import type { Stage } from "../lib/api/types";
import { ModelOutputPanel } from "./ModelOutputPanel";

/** Every stored analysis stage with its status, reason and duration; a completed stage with
 * model output shows the uncalibrated output panel. */
export function StageList({
  stages,
  modelVersions,
}: {
  stages: Record<string, Stage>;
  modelVersions: Record<string, string>;
}) {
  const names = Object.keys(stages);
  if (names.length === 0) return <p>No analysis stages were recorded.</p>;
  return (
    <ul className="stage-list">
      {names.map((name) => {
        const stage = stages[name];
        if (stage === undefined) return null;
        const complete = stage.status === "complete";
        return (
          <li key={name} className="stage">
            <h4>{stageLabel(name)}</h4>
            <dl className="facts">
              <dt>Status</dt>
              <dd>{complete ? "Complete" : "Unavailable"}</dd>
              {complete ? null : (
                <>
                  <dt>Reason</dt>
                  <dd>
                    {reasonLabel(stage.reason)}
                    {stage.reason ? <span className="shell-meta"> ({stage.reason})</span> : null}
                  </dd>
                  <dt>Impact</dt>
                  <dd>No score from this stage; it is not treated as safe.</dd>
                </>
              )}
              <dt>Stage time</dt>
              <dd>{stage.duration_ms} ms</dd>
            </dl>
            {stage.model_output ? (
              <ModelOutputPanel output={stage.model_output} modelVersion={modelVersions[name] ?? null} />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
