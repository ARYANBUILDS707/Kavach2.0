// Sign in (FRONTEND_MVP1_PLAN.md section 5, DESIGN.md "Sign in"). Generic credential errors,
// a Retry-After countdown when throttled, and the password cleared after every attempt.
import { useEffect, useState, type SyntheticEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router";

import { PUBLIC_HOME, safeNext } from "../../app/routes";
import { useSession } from "../../app/SessionProvider";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { CopyableId } from "../../components/CopyableId";
import { Field } from "../../components/Field";
import { SiteFooter } from "../../components/SiteFooter";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Wordmark } from "../../components/Wordmark";
import { isApiError } from "../../lib/api/errors";

interface Failure {
  message: string;
  requestId: string | null;
}

function failureFor(error: unknown): Failure {
  if (!isApiError(error)) {
    return { message: "Something went wrong. Try again.", requestId: null };
  }
  const requestId = error.requestId;
  if (error.code === "INVALID_CREDENTIALS") {
    return { message: "Username or password is incorrect.", requestId };
  }
  if (error.code === "CSRF_REJECTED") {
    return {
      message: "This page must be opened from the configured address. Reload and try again.",
      requestId,
    };
  }
  if (error.status === 429) return { message: "Too many sign-in attempts.", requestId };
  if (error.status === 503) {
    return { message: "Sign-in is temporarily unavailable. Try again shortly.", requestId };
  }
  if (error.code === "NETWORK_ERROR" || error.code === "TIMEOUT") {
    return { message: "Can't reach the server. Check the connection.", requestId: null };
  }
  return { message: "Sign-in failed. Try again.", requestId };
}

export function LoginPage() {
  const { state, signIn } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [waitSeconds, setWaitSeconds] = useState(0);

  useEffect(() => {
    if (waitSeconds <= 0) return;
    const timer = setTimeout(() => {
      setWaitSeconds((value) => value - 1);
    }, 1000);
    return () => {
      clearTimeout(timer);
    };
  }, [waitSeconds]);

  if (state.status === "signedIn") return <Navigate to={next} replace />;

  const reason = (location.state as { reason?: string } | null)?.reason;

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setFailure(null);
    try {
      await signIn(username, password);
      void navigate(next, { replace: true });
    } catch (error) {
      setFailure(failureFor(error));
      if (isApiError(error) && error.status === 429) {
        setWaitSeconds(error.retryAfterSeconds ?? 60);
      }
    } finally {
      setPassword("");
      setPending(false);
    }
  }

  return (
    <div className="login-page">
      <header className="login-top">
        <Link to={PUBLIC_HOME} className="wordmark-link" aria-label="KAVACH public site">
          <Wordmark />
        </Link>
        <ThemeToggle />
      </header>
      <main id="main" className="login-layout">
        <section className="login-intro" aria-labelledby="login-intro-heading">
          <p className="eyebrow">Operator console · SMS fraud intelligence</p>
          <h2 id="login-intro-heading">
            <span className="hl hl-sun">Evidence first.</span> Judgement second.
          </h2>
          <p>
            Review stored SMS evidence, incident history and the honest state of the SMS model, in
            one analyst workspace.
          </p>
          <ul className="chip-list">
            <li>No public sign-up</li>
            <li>Message text is never stored</li>
            <li>Role-based access</li>
          </ul>
        </section>
        <section className="card login" aria-labelledby="login-heading">
          <h1 id="login-heading">Sign in to KAVACH</h1>
          <p className="shell-meta">Controlled demonstration. Accounts are provided by the operator.</p>
          {reason === "expired" ? <Banner>Your session ended. Sign in again to continue.</Banner> : null}
          {reason === "signedOut" ? <Banner>You have signed out.</Banner> : null}
          {failure ? (
            <Banner tone="error">
              {failure.message}
              {waitSeconds > 0 ? ` You can try again in ${String(waitSeconds)} seconds.` : null}
              {failure.requestId ? (
                <>
                  {" "}
                  <CopyableId label="Request ID" value={failure.requestId} />
                </>
              ) : null}
            </Banner>
          ) : null}
          <form
            onSubmit={(event) => {
              void handleSubmit(event);
            }}
          >
            <Field
              label="Username"
              name="username"
              autoComplete="username"
              required
              maxLength={80}
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
              }}
            />
            <Field
              label="Password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={256}
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
            />
            <Button
              type="submit"
              pending={pending}
              pendingLabel="Signing in…"
              disabled={waitSeconds > 0}
            >
              Sign in
            </Button>
          </form>
          <p className="login-foot">
            Looking for the public site? <Link to={PUBLIC_HOME}>See what KAVACH does</Link>
          </p>
        </section>
      </main>
      <SiteFooter compact />
    </div>
  );
}
