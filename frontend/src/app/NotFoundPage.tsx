import { Link } from "react-router";

import { StateView } from "../components/StateView";

export function NotFoundPage() {
  return (
    <main id="main" className="shell-main">
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
