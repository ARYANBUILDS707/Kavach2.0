import { Link } from "react-router";

import { StateView } from "../components/StateView";
import { Wordmark } from "../components/Wordmark";
import { PUBLIC_HOME } from "./routes";

export function NotFoundPage() {
  return (
    <main id="main" className="not-found">
      <p>
        <Link to={PUBLIC_HOME} className="wordmark-link" aria-label="KAVACH home">
          <Wordmark />
        </Link>
      </p>
      <StateView
        pageHeading
        state={{
          kind: "notFound",
          title: "Page not found",
          message: "This address does not match any page.",
        }}
        action={<Link to={PUBLIC_HOME}>Go to the start page</Link>}
      />
    </main>
  );
}
