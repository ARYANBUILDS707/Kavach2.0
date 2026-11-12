// Public product page (no session needed, no API calls). Everything stated here is either a fixed
// property of this release (no public sign-up, no message text kept, role-based access) or
// explicitly hedged; the live model state is only ever shown inside the app, after sign-in.
import { useState, type CSSProperties } from "react";
import { Link } from "react-router";

import { EXAMPLES } from "../../app/routes";
import { Button } from "../../components/Button";
import {
  HeroShield,
  HistoryIllustration,
  StagesIllustration,
  SubmitIllustration,
  SystemIllustration,
} from "../../components/Illustrations";
import { SiteFooter } from "../../components/SiteFooter";
import { SiteHeader } from "../../components/SiteHeader";

const TICKER = [
  "Recorded examples",
  "Fictional messages only",
  "Evidence, not message text",
  "Honest analysis status",
  "No login needed",
  "Unknown stays unknown",
];

const CAPABILITIES = [
  {
    tone: "saffron",
    title: "Controlled SMS submission",
    body: "Admins submit a synthetic message through the session, CSRF and origin checks. Each submission is stored once, with identifiers made in the browser.",
    chips: ["Admin only", "Session + CSRF", "No automatic retries"],
    art: <SubmitIllustration />,
  },
  {
    tone: "blue",
    title: "Incident history",
    body: "Filter recent records by channel, kind, tier and event time, then page through them newest first.",
    chips: ["Filters in the URL", "Cursor paging"],
    art: <HistoryIllustration />,
  },
  {
    tone: "sun",
    title: "Evidence and analysis status",
    body: "Every analysis stage is recorded with its status, reason and timing. A missing stage is shown as missing, never as safe.",
    chips: ["Per-stage reasons", "Assessment revisions"],
    art: <StagesIllustration />,
  },
  {
    tone: "pink",
    title: "System and model readiness",
    body: "See whether the SMS model can run, why it cannot, and which version is pinned. Readiness is never presented as accuracy.",
    chips: ["Operational state", "Uncalibrated outputs labelled"],
    art: <SystemIllustration />,
  },
] as const;

const WORKFLOW = [
  {
    step: "01",
    label: "SUBMIT",
    title: "A synthetic message",
    body: "An admin enters fictional text. The browser adds a fresh event identifier and a synthetic subscriber token.",
  },
  {
    step: "02",
    label: "CHECK",
    title: "Access and limits",
    body: "The server checks the session, role, CSRF token, origin and submission quota before it reads the message.",
  },
  {
    step: "03",
    label: "RECORD",
    title: "Evidence, not text",
    body: "Analysis stages are stored with their status and reasons. When the model is off, the stage says so.",
  },
  {
    step: "04",
    label: "REVIEW",
    title: "History and detail",
    body: "Analysts open the incident, read the evidence timeline and the current assessment, with scores left empty when none exist.",
  },
];

const FAQ = [
  {
    q: "Is there a login or sign-up?",
    a: "No. This public site has no accounts, no sign-up and no login. The operator console described below is separate and is not open to visitors.",
  },
  {
    q: "Are the examples live?",
    a: "No. They are the pinned model's recorded outputs for fixed, fictional messages, taken in a local offline run. Nothing is analysed when you visit.",
  },
  {
    q: "Can I try my own message?",
    a: "Not on this site: it has no input box. Live analysis is a local research feature for fictional messages, and a public analyzer would need its own authorization, privacy review and abuse limits first.",
  },
  {
    q: "Does KAVACH keep message text?",
    a: "This site never receives message text. In the operator console, a submitted message is analysed once and only the evidence is kept; the text is not stored or shown, and evidence expires after 7 days.",
  },
  {
    q: "Is the model score a probability?",
    a: "No. The SMS model's native outputs are uncalibrated and labelled as such. Risk tiers stay unknown until a calibration validated on KAVACH data exists.",
  },
];

function Ticker() {
  // Decorative: every phrase is stated again in the sections below.
  const words = [...TICKER, ...TICKER];
  return (
    <div className="ticker" aria-hidden="true">
      <div className="ticker-track">
        {words.map((word, index) => (
          <span key={`${word}-${String(index)}`}>
            {word}
            <i />
          </span>
        ))}
      </div>
    </div>
  );
}

export function LandingPage() {
  // One control pauses all continuous decorative motion (ticker, floating mark, status pulse) for
  // this visit. Held in memory only. Under reduced motion nothing moves and the control is hidden.
  const [motionPaused, setMotionPaused] = useState(false);
  return (
    <>
      <SiteHeader />

      <main id="main" className="landing-main" data-motion={motionPaused ? "paused" : "running"}>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-art dot-grid">
            <HeroShield />
            <span className="hero-art-tag">
              KAVACH <span className="version-pill">2.0</span>
            </span>
          </div>
          <div className="hero-copy">
            <p className="status-pill">
              <span className="status-dot" aria-hidden="true" />
              Controlled research demonstration
            </p>
            <p className="sticker">
              <span className="sticker-badge" aria-hidden="true">
                SMS
              </span>
              <span className="sticker-text">
                <b>Fraud intelligence</b>
                <small>MVP-1 · evidence first</small>
              </span>
            </p>
            <h1 id="hero-title" className="hero-title">
              <span>Read the signal.</span> <span className="hl hl-sun">Keep the evidence.</span>{" "}
              <span className="hl hl-blue">Decide with care.</span>
            </h1>
            <p className="hero-lead">
              KAVACH is an evidence-first research project for SMS fraud analysis. Browse what its
              model recorded for fictional messages, and what it deliberately does not claim.
              Nothing to sign in to.
            </p>
            <ul className="fact-chips" aria-label="At a glance">
              <li>
                <b>SMS</b>
                <span>Channel in this release</span>
              </li>
              <li>
                <b>No login</b>
                <span>Open to every visitor</span>
              </li>
              <li>
                <b>Recorded</b>
                <span>Examples, not live analysis</span>
              </li>
            </ul>
            <div className="cta-row">
              <Link to={EXAMPLES} className="button button-primary button-lg">
                See recorded examples
              </Link>
              <a href="#workflow" className="button button-secondary button-lg">
                How it works
              </a>
            </div>
            {/* The visible label carries the state, so it is not also marked aria-pressed. */}
            <Button
              variant="secondary"
              className="motion-toggle"
              onClick={() => {
                setMotionPaused((paused) => !paused);
              }}
            >
              {motionPaused ? "Resume motion" : "Pause motion"}
            </Button>
          </div>
        </section>

        <Ticker />

        <section id="about" className="landing-section reveal" aria-labelledby="about-title">
          <h2 id="about-title" className="landing-title">
            About KAVACH
          </h2>
          <p className="about-statement">
            Kavach (<span lang="sa">कवच</span>) means <em>armour</em>. Here it is a careful place to
            look at suspicious SMS evidence, where a missing signal is never mistaken for a safe
            one.
          </p>
        </section>

        <section id="platform" className="landing-section reveal" aria-labelledby="platform-title">
          <p className="eyebrow">The platform today</p>
          <h2 id="platform-title" className="landing-title">
            What KAVACH does now.
          </h2>
          <div className="platform-grid">
            <article className="card">
              <span className="number-tag">01</span>
              <h3>Collects evidence safely</h3>
              <p>
                In the operator console, SMS events arrive through authenticated ingestion or the
                admin submission page. Each is stored once, and the message text is not kept.
              </p>
            </article>
            <article className="card">
              <span className="number-tag">02</span>
              <h3>Shows what was analysed</h3>
              <p>
                Incidents record each analysis stage, its status and why it was unavailable,
                alongside the current assessment and its revision.
              </p>
            </article>
            <article className="card">
              <span className="number-tag">03</span>
              <h3>Says what it doesn&apos;t know</h3>
              <p>
                With no validated calibration, scores stay empty and tiers stay unknown. The page
                tells you that instead of guessing.
              </p>
            </article>
          </div>
        </section>

        <section id="capabilities" className="landing-section" aria-labelledby="capabilities-title">
          <p className="eyebrow">Capabilities</p>
          <h2 id="capabilities-title" className="landing-title">
            Four tools. One workspace.
          </h2>
          <p className="section-note">
            These are the tools in KAVACH&apos;s operator console, which is not open to visitors.
            This public site shows recorded examples instead.
          </p>
          <div className="capability-grid">
            {CAPABILITIES.map((capability) => (
              <article
                key={capability.title}
                className={`card card-interactive capability capability-${capability.tone} reveal`}
              >
                {capability.art}
                <h3>{capability.title}</h3>
                <p>{capability.body}</p>
                <ul className="chip-list">
                  {capability.chips.map((chip) => (
                    <li key={chip}>{chip}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section id="workflow" className="landing-section" aria-labelledby="workflow-title">
          <p className="eyebrow">Workflow</p>
          <h2 id="workflow-title" className="landing-title">
            From message to evidence.
          </h2>
          <p className="section-note">How the operator console handles a fictional message.</p>
          <ol className="workflow-list">
            {WORKFLOW.map((item) => (
              <li key={item.step} className="reveal">
                <article className="ticket">
                  <div className="ticket-top" aria-hidden="true">
                    <small>{item.label}</small>
                    <b>{item.step}</b>
                  </div>
                  <div className="ticket-body">
                    <h3>
                      <span className="visually-hidden">Step {item.step}: </span>
                      {item.title}
                    </h3>
                    <p>{item.body}</p>
                  </div>
                </article>
              </li>
            ))}
          </ol>
        </section>

        <section id="principles" className="landing-section reveal" aria-labelledby="principles-title">
          <p className="eyebrow">Principles</p>
          <h2 id="principles-title" className="landing-title">
            How it treats evidence.
          </h2>
          <div className="principles">
            <article className="principle">
              <h3>Text stays out</h3>
              <p>
                Message text is not stored, shown, put in URLs or kept in the browser. Analysts
                work from analysis evidence.
              </p>
            </article>
            <article className="principle">
              <h3>Nothing public to leak</h3>
              <p>
                This site holds only fixed, fictional examples. The operator console checks the
                session and role on the server for every request, and it is not linked from here.
              </p>
            </article>
            <article className="principle">
              <h3>Unknown stays unknown</h3>
              <p>
                An unavailable model or a missing calibration is reported plainly. Nothing is
                treated as safe because a signal is absent.
              </p>
            </article>
          </div>
        </section>

        <section id="status" className="landing-section reveal" aria-labelledby="status-title">
          <div className="card status-board">
            <div>
              <p className="eyebrow">Release status</p>
              <h2 id="status-title" className="visually-hidden">
                Release status
              </h2>
              <p className="status-big">MVP-1</p>
            </div>
            <p>
              KAVACH is a controlled demonstration, not a production service. The SMS model is
              disabled by default and is not validated on KAVACH data. The examples on this site
              are recorded outputs, not live analysis.
            </p>
            <dl className="status-rows">
              <div className="status-row" style={{ "--swatch": "var(--mint)" } as CSSProperties}>
                <dt>SMS evidence and incidents</dt>
                <dd>In this release</dd>
              </div>
              <div className="status-row" style={{ "--swatch": "var(--sun)" } as CSSProperties}>
                <dt>SMS model</dt>
                <dd>Off by default · not validated</dd>
              </div>
              <div className="status-row" style={{ "--swatch": "var(--saffron)" } as CSSProperties}>
                <dt>Risk tiers and scores</dt>
                <dd>Unknown until calibrated</dd>
              </div>
              <div className="status-row">
                <dt>Live analysis of visitors&apos; messages</dt>
                <dd>Not available</dd>
              </div>
              <div className="status-row">
                <dt>Voice and cross-channel correlation</dt>
                <dd>Not in this release</dd>
              </div>
            </dl>
          </div>
        </section>

        <section id="questions" className="landing-section reveal" aria-labelledby="questions-title">
          <div className="faq-layout">
            <h2 id="questions-title" className="landing-title">
              Questions
            </h2>
            <div>
              {FAQ.map((item) => (
                <details key={item.q} className="faq-item">
                  <summary>{item.q}</summary>
                  <p>{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="cta-band reveal" aria-labelledby="cta-title">
          <h2 id="cta-title">Ready to look at the evidence?</h2>
          <p>See what the model said about nine fictional messages, and what it does not claim.</p>
          <Link to={EXAMPLES} className="button button-primary button-lg">
            See the recorded examples
          </Link>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
