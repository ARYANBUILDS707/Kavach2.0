import { Link } from "react-router";

import { Wordmark } from "./Wordmark";

/** Closing band shared by the public pages; `compact` is the one-line version inside the app.
 * Its wording deliberately avoids phrases the pages themselves state (tests match those). */
export function SiteFooter({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <footer className="app-footer">
        <span>KAVACH 2.0</span>
        <span>SMS fraud-intelligence research MVP. Analysis evidence only; no message text is kept.</span>
      </footer>
    );
  }
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="site-footer-brand">
          <Wordmark />
          <p>
            An SMS fraud-intelligence workspace for analysts, built as a controlled research
            demonstration.
          </p>
        </div>
        <nav aria-label="Footer" className="site-footer-nav">
          <ul>
            <li>
              <a href="/welcome#platform">Platform</a>
            </li>
            <li>
              <a href="/welcome#capabilities">Capabilities</a>
            </li>
            <li>
              <a href="/welcome#status">Status</a>
            </li>
            <li>
              <Link to="/login">Analyst sign-in</Link>
            </li>
          </ul>
        </nav>
        <p className="site-footer-note">
          Accounts are provisioned by an operator. KAVACH makes no accuracy, security or compliance
          claims for this demonstration.
        </p>
      </div>
    </footer>
  );
}
