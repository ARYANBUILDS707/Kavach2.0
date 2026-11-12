import { Link } from "react-router";

import { useModelStatus } from "../app/ModelStatusProvider";
import { MODEL_STATE_LABELS } from "../lib/format";

/** Header indicator for the SMS model; links to the System page for detail. */
export function ModelStatePill() {
  const { status, error, loading } = useModelStatus();
  let text = "checking…";
  let state = "checking";
  if (status !== null) {
    text = MODEL_STATE_LABELS[status.state];
    state = status.state;
  } else if (error !== null && !loading) {
    text = "status unknown";
    state = "unknown";
  }
  return (
    <Link to="/system" className={`pill pill-model-${state}`}>
      SMS model: {text}
    </Link>
  );
}
