import { type FormEvent, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { formatTime } from "../app/format";
import { safeNext } from "../app/navigation";
import { useMe, useSignIn } from "../app/session";
import { type Theme, applyTheme, storedTheme } from "../app/theme";

/** A drifting trend against its flat expected value, drawn once for the cover. */
function coverPaths(): [string, string] {
  let a = "M0 470";
  let b = "M0 470";
  for (let i = 1; i <= 90; i++) {
    const x = i * 10;
    const wobble = Math.sin(i * 1.7) * 6 + Math.cos(i * 0.9) * 4;
    const drift = i > 50 ? ((i - 50) / 40) ** 2 * 210 : 0;
    a += ` L${x} ${(470 + wobble - drift).toFixed(1)}`;
    b += ` L${x} ${(470 + Math.sin(i * 1.3) * 5).toFixed(1)}`;
  }
  return [a, b];
}
const [COVER_A, COVER_B] = coverPaths();

export function SignInPage() {
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const me = useMe();
  const signIn = useSignIn();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [caps, setCaps] = useState(false);
  const [tried, setTried] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState<Theme>(storedTheme);

  if (me.data) return <Navigate to={next} replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTried(true);
    if (!username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      void navigate(next, { replace: true });
    } catch (caught) {
      setPassword("");
      setError(
        caught instanceof ApiError && caught.status !== 401
          ? caught.message
          : "Sign-in failed. Check your user name and password, or contact your administrator.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <div className="login">
        <div className="cover" aria-hidden="true">
          <svg viewBox="0 0 900 900" preserveAspectRatio="xMidYMid slice">
            <rect width="900" height="900" style={{ fill: "var(--traverse-surface-raised)" }} />
            <g
              style={{
                fill: "none",
                stroke: "var(--traverse-border-strong)",
                strokeWidth: 1,
                opacity: 0.55,
              }}
            >
              <path d="M0 160H900M0 280H900M0 400H900M0 520H900M0 640H900" />
              <path d="M120 0V900M300 0V900M480 0V900M660 0V900M840 0V900" />
            </g>
            <path
              d={COVER_A}
              style={{ fill: "none", stroke: "var(--traverse-chart-series-1)", strokeWidth: 3 }}
            />
            <path
              d={COVER_B}
              style={{
                fill: "none",
                stroke: "var(--traverse-chart-series-5)",
                strokeWidth: 2,
                strokeDasharray: "8 6",
              }}
            />
            <line
              x1="0"
              x2="900"
              y1="300"
              y2="300"
              style={{
                stroke: "var(--traverse-status-warning-fg)",
                strokeWidth: 2,
                strokeDasharray: "10 8",
              }}
            />
            <g
              style={{
                fill: "var(--traverse-surface-panel)",
                stroke: "var(--traverse-border-strong)",
                strokeWidth: 2,
              }}
            >
              <rect x="90" y="610" width="200" height="120" rx="10" />
              <circle cx="190" cy="670" r="38" />
              <rect x="360" y="580" width="150" height="150" rx="10" />
              <rect x="560" y="640" width="260" height="90" rx="10" />
            </g>
            <path
              d="M290 670H360M510 690H560"
              style={{ fill: "none", stroke: "var(--traverse-chart-series-1)", strokeWidth: 3 }}
            />
          </svg>
          <div className="cap2">
            <p style={{ fontSize: 24, fontWeight: 600 }}>See equipment drift before the alarm.</p>
            <p className="sec" style={{ marginTop: 4 }}>
              Every machine compared with its own normal, every minute.
            </p>
          </div>
        </div>
        <div className="form">
          <form className="box" onSubmit={submit} noValidate aria-label="Sign in">
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <b style={{ fontSize: 24 }}>Traverse</b>
              <span
                style={{ fontSize: 20, fontWeight: 600, color: "var(--traverse-action-primary)" }}
              >
                PM
              </span>
            </div>
            <div className="notice">For authorized users only. Sign-in attempts are recorded.</div>
            <div className="fld">
              <label htmlFor="lg-u">User name or e-mail</label>
              <input
                id="lg-u"
                className="in"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
              {tried && !username.trim() && (
                <span className="err">Enter your user name or e-mail.</span>
              )}
            </div>
            <div className="fld">
              <label htmlFor="lg-p">Password</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  id="lg-p"
                  className="in"
                  name="password"
                  type={shown ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyUp={(e) => setCaps(e.getModifierState("CapsLock"))}
                />
                <button
                  className="btn btn-s"
                  type="button"
                  aria-pressed={shown}
                  onClick={() => setShown(!shown)}
                  style={{ height: 44 }}
                >
                  {shown ? "Hide" : "Show"}
                </button>
              </div>
              {caps && (
                <span className="err" style={{ color: "var(--traverse-status-warning-fg)" }}>
                  Caps Lock is on.
                </span>
              )}
              {tried && !password && <span className="err">Enter your password.</span>}
            </div>
            {error && (
              <div className="notice bad" role="alert">
                {error}
              </div>
            )}
            <button
              className="btn btn-p"
              type="submit"
              disabled={busy}
              style={{ height: 44, width: "100%" }}
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
            <p className="sec s13">Forgotten password? Contact your site administrator.</p>
            <div className="statusbar">
              <span>Traverse PM</span>
              <span className={`pill ${navigator.onLine ? "p-info" : "p-warning"}`}>
                <span className="d" />
                {navigator.onLine ? "Browser online" : "Browser offline"}
              </span>
              <span>{formatTime(new Date())}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                className="btn btn-g btn-sm"
                type="button"
                onClick={() => {
                  const nextTheme: Theme = theme === "day" ? "night" : "day";
                  applyTheme(nextTheme);
                  setTheme(nextTheme);
                }}
              >
                {theme === "day" ? "Switch to night mode" : "Switch to day mode"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
