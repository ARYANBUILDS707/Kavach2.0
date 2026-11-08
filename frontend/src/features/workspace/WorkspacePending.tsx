import { useSession } from "../../app/SessionProvider";

/** The signed-in landing for MVP-F1. The analyst pages arrive in MVP-F2; nothing here implies
 * that they exist yet. */
export function WorkspacePending() {
  const { state } = useSession();
  const name = state.status === "signedIn" ? state.session.user.display_name : "";
  return (
    <>
      <h1>Signed in</h1>
      <p>Welcome, {name}. The analyst views are not available in this build yet.</p>
    </>
  );
}
