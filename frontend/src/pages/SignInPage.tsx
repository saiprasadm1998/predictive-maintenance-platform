import { type FormEvent, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { safeNext } from "../app/navigation";
import { useMe, useSignIn } from "../app/session";

export function SignInPage() {
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const me = useMe();
  const signIn = useSignIn();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me.data) return <Navigate to={next} replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      void navigate(next, { replace: true });
    } catch (caught) {
      setPassword("");
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Sign-in failed for an unexpected reason. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="signin">
      <form className="panel signin-form" onSubmit={submit} aria-labelledby="signin-title">
        <h1 id="signin-title" className="signin-title">
          Predictive Maintenance Platform
        </h1>
        <p className="muted">Sign in to continue.</p>
        <label className="field">
          <span>Username</span>
          <input
            className="control"
            name="username"
            autoComplete="username"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            className="control"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <div role="alert" className="form-error">
          {error}
        </div>
        <button type="submit" className="button button-primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
