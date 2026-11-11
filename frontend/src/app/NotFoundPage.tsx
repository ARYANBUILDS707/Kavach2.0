import { Link } from "react-router";

import { StateView } from "../components/StateView";
import { Wordmark } from "../components/Wordmark";

export function NotFoundPage() {
  return (
    <main id="main" className="not-found">
      <p>
        <Link to="/welcome" className="wordmark-link" aria-label="KAVACH home">
          <Wordmark />
        </Link>
      </p>
      <StateView
        state={{
          kind: "notFound",
          title: "Page not found",
          message: "This address does not match any page.",
        }}
        action={<Link to="/">Go to the start page</Link>}
      />
    </main>
  );
}
