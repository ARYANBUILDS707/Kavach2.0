import { Link } from "react-router";

import { EXAMPLES, PUBLIC_ANALYZE, PUBLIC_HOME } from "../app/routes";
import { ThemeToggle } from "./ThemeToggle";
import { Wordmark } from "./Wordmark";

/** Header of the public pages. There is deliberately no sign-in or sign-up here: the public site
 * has no accounts, and the operator console is not linked from it. The section links use `/#id`
 * so they work from every public page. */
export function SiteHeader({ current }: { current?: "examples" | "analyze" }) {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="site-nav">
        <Link to={PUBLIC_HOME} className="wordmark-link" aria-label="KAVACH home">
          <Wordmark />
        </Link>
        <nav className="site-nav-links" aria-label="Site">
          <ul>
            <li>
              <a href="/#about">About</a>
            </li>
            <li>
              <a href="/#platform">Platform</a>
            </li>
            <li>
              <a href="/#capabilities">Capabilities</a>
            </li>
            <li>
              <a href="/#status">Status</a>
            </li>
          </ul>
        </nav>
        <div className="site-nav-end">
          <ThemeToggle />
          <Link to={PUBLIC_ANALYZE} className="button button-secondary button-sm"
            {...(current === "analyze" ? { "aria-current": "page" as const } : {})}>Analyze SMS</Link>
          <Link
            to={EXAMPLES}
            className="button button-primary button-sm"
            {...(current === "examples" ? { "aria-current": "page" as const } : {})}
          >
            Examples
          </Link>
        </div>
      </header>
    </>
  );
}
