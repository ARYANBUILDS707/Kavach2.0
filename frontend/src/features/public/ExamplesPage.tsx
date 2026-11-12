// Public, login-free demonstration view. Everything here is static: fixed fictional messages and
// the outputs a local, offline run of the pinned model recorded for them. The page makes no API
// request, has no input box, and never presents these results as live analysis.
import { Banner } from "../../components/Banner";
import { PageHeader } from "../../components/PageHeader";
import { SiteFooter } from "../../components/SiteFooter";
import { SiteHeader } from "../../components/SiteHeader";
import { formatModelValue } from "../../lib/format";
import { RECORDED, type RecordedExample } from "./examples";

const PREDICTION_NAMES: Record<string, string> = {
  legitimate: "Legitimate",
  spam: "Spam",
  fraud: "Fraud",
};
const SCORE_ORDER = ["legitimate", "spam", "fraud"] as const;

function formatRecordedDate(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function ExampleCard({ example }: { example: RecordedExample }) {
  const headingId = `example-${example.id}`;
  return (
    <li>
      <article className="card example-card" aria-labelledby={headingId}>
        <p className="eyebrow">Fictional message</p>
        <h2 id={headingId}>{example.scenario}</h2>
        <blockquote className="example-text">{example.text}</blockquote>
        <p className="example-prediction">
          Recorded prediction:{" "}
          <strong>{PREDICTION_NAMES[example.prediction] ?? example.prediction}</strong>
        </p>
        <dl className="facts">
          {SCORE_ORDER.map((name) => (
            <div key={name} className="example-score">
              <dt>{PREDICTION_NAMES[name]} score</dt>
              <dd className="numeric">
                {example.labels[name] === undefined ? "Not available" : formatModelValue(example.labels[name])}
              </dd>
            </div>
          ))}
        </dl>
      </article>
    </li>
  );
}

export function ExamplesPage() {
  return (
    <>
      <SiteHeader current="examples" />
      <main id="main" className="public-main">
        <PageHeader
          eyebrow="Recorded examples"
          title="What the model said about fictional messages"
          lead="Nine invented messages and the answer KAVACH's pinned model recorded for each. A look at the evidence, not a service you can use."
        />

        <Banner>
          <strong>These are recorded examples, not live analysis.</strong> Nothing on this page is
          analysed when you visit, and there is deliberately no box to type a message into. This
          site has no login, no accounts and keeps no messages.
        </Banner>

        <section className="card example-notes" aria-labelledby="example-notes-heading">
          <h2 id="example-notes-heading">How to read these results</h2>
          <dl className="facts">
            <dt>Recorded on</dt>
            <dd>{formatRecordedDate(RECORDED.recorded_on)} (UTC)</dd>
            <dt>Model version</dt>
            <dd>
              <span className="copyable-id">{RECORDED.model_version}</span>
            </dd>
            <dt>How it was run</dt>
            <dd>A local, offline run on a developer machine, using only the fictional messages below.</dd>
            <dt>What a prediction is</dt>
            <dd>
              The class the model scored highest. It is a model prediction, not an established fact,
              and a person would decide what a message really is.
            </dd>
            <dt>What the scores are</dt>
            <dd>
              Native model scores, uncalibrated: they are not probabilities and not a risk level.
            </dd>
            <dt>Validated?</dt>
            <dd>
              No. The model is not validated on KAVACH data, and no accuracy figure is claimed from
              nine hand-written messages.
            </dd>
          </dl>
        </section>

        <ul className="example-grid" aria-label="Recorded examples">
          {RECORDED.examples.map((example) => (
            <ExampleCard key={example.id} example={example} />
          ))}
        </ul>

        <section className="card example-notes" aria-labelledby="own-message-heading">
          <h2 id="own-message-heading">Want to try your own message?</h2>
          <p>
            Hosted analysis is not enabled. The Analyze SMS page supports authorized local fictional
            testing; public use still requires owner approval and privacy, security and release checks.
            Today, live analysis is a local research feature that works on fictional messages only.
          </p>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
