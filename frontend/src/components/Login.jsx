import { useState, useRef } from "react";
import {
  ORG_DOMAIN,
  isFirebaseConfigured,
  signInWithEmailPassword,
  signUpWithEmailPassword,
  signInWithGoogle,
  signInWithMicrosoft,
  sendPasswordReset,
  mapFirebaseAuthError,
  linkPendingCredential,
} from "../services/authService";

/** Firebase `fetchSignInMethodsForEmail` ids — OIDC Microsoft may use `oidc.azure-ad`. */
function formatExistingProviders(methods) {
  if (!methods?.length) return "your existing sign-in";
  return methods
    .map((m) => {
      if (m === "google.com") return "Google";
      if (m === "microsoft.com") return "Microsoft";
      if (m === "password") return "email/password";
      if (String(m).includes("oidc.") || String(m).includes("azure")) return "Microsoft";
      return String(m);
    })
    .join(", ");
}

function Logo({ light }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <img
        src="/relanto-logo.png" alt="Relanto"
        style={{ height: 32, objectFit: "contain", borderRadius: 4 }}
      />
      <div style={{ width: 1, height: 22, background: light ? "rgba(255,255,255,.2)" : "rgba(27,38,79,.15)", flexShrink: 0 }} />
      <span style={{
        fontSize: 15, fontWeight: 700, letterSpacing: "-.3px",
        color: light ? "#fff" : "#1B264F",
      }}>Knowledge Assist</span>
    </div>
  );
}

export function LoginPage({ onLogin, theme }) {
  const [isSignUp, setIsSignUp] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [remember, setRemember] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [resetSent, setResetSent] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [microsoftLoading, setMicrosoftLoading] = useState(false);
  /** Pending OAuth credential to attach after user signs in with the provider that already owns the email. */
  const pendingLinkCredRef = useRef(null);
  /** UI for account-exists-with-different-credential linking flow. */
  const [linkPrompt, setLinkPrompt] = useState(null);

  const bg = "var(--bg)";
  const card = "var(--bg2)";
  const cardBorder = "var(--border)";
  const txt = "var(--text0)";
  const sub = "var(--text2)";
  const inpBorder = "var(--border2)";
  const inp = "var(--bg3)";

  const resetForm = (nextIsSignUp) => {
    setIsSignUp(nextIsSignUp);
    setFullName("");
    setEmail("");
    setPassword("");
    setConfirmPassword("");
    setShowPass(false);
    setRemember(false);
    setError("");
    setResetSent(false);
    setLoading(false);
    pendingLinkCredRef.current = null;
    setLinkPrompt(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isFirebaseConfigured) {
      setError("Set VITE_FIREBASE_API_KEY and VITE_FIREBASE_AUTH_DOMAIN in .env, then restart the dev server.");
      return;
    }
    if (isSignUp) {
      if (!fullName || !email || !password || !confirmPassword) {
        setError("Please fill in all required fields.");
        return;
      }
      if (password.length < 6) {
        setError("Password must be at least 6 characters.");
        return;
      }
      if (password !== confirmPassword) {
        setError("Passwords do not match.");
        return;
      }
    } else if (!email || !password) {
      setError("Please fill in all fields.");
      return;
    }

    setLoading(true);
    setError("");
    setResetSent(false);
    try {
      let user = isSignUp
        ? await signUpWithEmailPassword({ name: fullName, email, password })
        : await signInWithEmailPassword(email, password);
      if (!isSignUp && pendingLinkCredRef.current) {
        user = await linkPendingCredential(pendingLinkCredRef.current);
        pendingLinkCredRef.current = null;
        setLinkPrompt(null);
      }
      onLogin?.(user);
    } catch (err) {
      setError(mapFirebaseAuthError(err));
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPassword = async () => {
    if (!isFirebaseConfigured) {
      setError("Firebase is not configured.");
      return;
    }
    if (!email.trim()) {
      setError("Enter your email above, then click Forgot password.");
      return;
    }
    setError("");
    setResetSent(false);
    try {
      await sendPasswordReset(email);
      setResetSent(true);
    } catch (err) {
      setError(mapFirebaseAuthError(err));
    }
  };

  const handleGoogle = async () => {
    if (!isFirebaseConfigured) {
      setError("Set VITE_FIREBASE_API_KEY and VITE_FIREBASE_AUTH_DOMAIN in .env, then restart the dev server.");
      return;
    }
    setGoogleLoading(true);
    setError("");
    setResetSent(false);
    try {
      let user = await signInWithGoogle();
      if (pendingLinkCredRef.current) {
        user = await linkPendingCredential(pendingLinkCredRef.current);
        pendingLinkCredRef.current = null;
        setLinkPrompt(null);
      }
      onLogin?.(user);
    } catch (err) {
      if (err?.code === "auth/account-exists-with-different-credential" && err.pendingCredential) {
        pendingLinkCredRef.current = err.pendingCredential;
        setLinkPrompt({
          email: err.email,
          attemptedProvider: err.attemptedProvider,
          methods: err.existingSignInMethods || [],
        });
        setError("");
        return;
      }
      setError(mapFirebaseAuthError(err));
    } finally {
      setGoogleLoading(false);
    }
  };

  const handleMicrosoft = async () => {
    if (!isFirebaseConfigured) {
      setError("Set VITE_FIREBASE_API_KEY and VITE_FIREBASE_AUTH_DOMAIN in .env, then restart the dev server.");
      return;
    }
    setMicrosoftLoading(true);
    setError("");
    setResetSent(false);
    try {
      let user = await signInWithMicrosoft();
      if (pendingLinkCredRef.current) {
        user = await linkPendingCredential(pendingLinkCredRef.current);
        pendingLinkCredRef.current = null;
        setLinkPrompt(null);
      }
      onLogin?.(user);
    } catch (err) {
      if (err?.code === "auth/account-exists-with-different-credential" && err.pendingCredential) {
        pendingLinkCredRef.current = err.pendingCredential;
        setLinkPrompt({
          email: err.email,
          attemptedProvider: err.attemptedProvider,
          methods: err.existingSignInMethods || [],
        });
        setError("");
        return;
      }
      setError(mapFirebaseAuthError(err));
    } finally {
      setMicrosoftLoading(false);
    }
  };

  const busy = googleLoading || microsoftLoading || loading;

  return (
    <div style={{
      display: "flex", height: "100vh", background: bg,
      transition: "background .3s", fontFamily: "'Plus Jakarta Sans', sans-serif",
    }}>

      <div style={{
        flex: "0 0 45%",
        background: "var(--login-grad)",
        display: "flex", flexDirection: "column",
        justifyContent: "space-between",
        padding: "40px 48px",
        position: "relative", overflow: "hidden",
      }}>
        <div style={{ position: "absolute", top: -60, right: -60, width: 260, height: 260, borderRadius: "50%", background: "var(--login-blob1)" }} />
        <div style={{ position: "absolute", bottom: 40, left: -60, width: 220, height: 220, borderRadius: "50%", background: "var(--login-blob2)" }} />
        <div style={{ position: "absolute", top: "50%", right: "15%", width: 140, height: 140, borderRadius: "50%", background: "var(--login-blob3)" }} />

        <Logo light={theme === 'relanto'} />

        <div style={{ position: "relative", zIndex: 1 }}>
          <div style={{
            fontSize: 32, fontWeight: 900, lineHeight: 1.2, marginBottom: 16,
            color: theme === 'relanto' ? "#fff" : "var(--text0)",
          }}>
            AI-Powered<br />
            <span style={{ color: theme === 'relanto' ? "#E8532E" : "var(--accent)" }}>Knowledge Assist</span>
          </div>
          <p style={{
            color: theme === 'relanto' ? "rgba(255,255,255,.7)" : "var(--text1)",
            fontSize: 14, lineHeight: 1.7, maxWidth: 340, marginBottom: 32,
          }}>
            Sales intelligence, market research, and deal qualification — all powered by AI-driven insights in one platform.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {[
              ["📈", "Sales Intelligence", "Pipeline & deal tracking"],
              ["🌍", "Market Research", "Trends & competitor analysis"],
              ["🤖", "AI Insights", "Smart recommendations"],
              ["🎯", "Qualification", "Structured deal reviews"],
            ].map(([icon, title, desc]) => (
              <div key={title} style={{
                background: theme === 'relanto' ? "rgba(255,255,255,.07)" : "rgba(255,255,255,.82)",
                borderRadius: 12,
                padding: "12px 14px", display: "flex", gap: 10, alignItems: "flex-start",
                border: theme === 'relanto' ? "1px solid rgba(255,255,255,.10)" : "1px solid var(--border)",
                boxShadow: theme === 'relanto' ? "none" : "0 2px 8px rgba(0,0,0,.04)",
                backdropFilter: theme === 'relanto' ? "blur(6px)" : "none",
              }}>
                <span style={{ fontSize: 20 }}>{icon}</span>
                <div>
                  <div style={{
                    color: theme === 'relanto' ? "#fff" : "var(--text0)",
                    fontWeight: 700, fontSize: 12,
                  }}>{title}</div>
                  <div style={{
                    color: theme === 'relanto' ? "rgba(255,255,255,.5)" : "var(--text2)",
                    fontSize: 11, marginTop: 2,
                  }}>{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p style={{
          color: theme === 'relanto' ? "rgba(255,255,255,.35)" : "var(--text3)",
          fontSize: 11, position: "relative", zIndex: 1,
        }}>
          © 2026 Relanto · AI-Powered Knowledge Platform
        </p>
      </div>

      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        padding: "40px 24px", position: "relative",
      }}>
        <div style={{
          width: "100%", maxWidth: 400,
          background: card, borderRadius: 20, padding: 36,
          border: `1px solid ${cardBorder}`,
          boxShadow: "0 18px 42px rgba(15,23,42,.10)",
          animation: "fadeUp .35s ease",
        }}>
          <div style={{ marginBottom: 28 }}>
            <div style={{ color: txt, fontSize: 22, fontWeight: 900, marginBottom: 6 }}>
              {isSignUp ? "Create account" : "Welcome back"}
            </div>
            <div style={{ color: sub, fontSize: 13 }}>
              {isSignUp ? "Sign up with your work email" : "Email and password, or Google / Microsoft"}
            </div>
          </div>

          {resetSent && (
            <div style={{
              background: "rgba(5,150,105,.1)", border: "1px solid rgba(5,150,105,.25)",
              borderRadius: 10, padding: "10px 14px", color: "#059669",
              fontSize: 12, marginBottom: 16,
            }}>
              Check your inbox for a password reset link.
            </div>
          )}

          {linkPrompt && (
            <div style={{
              background: "rgba(59,130,246,.12)", border: "1px solid rgba(59,130,246,.28)",
              borderRadius: 10, padding: "12px 14px", color: "#93C5FD",
              fontSize: 12, marginBottom: 16, lineHeight: 1.55,
            }}>
              <div style={{ fontWeight: 800, marginBottom: 6, color: "#BFDBFE" }}>Link this sign-in</div>
              <p style={{ margin: "0 0 10px", color: "var(--text1)" }}>
                {linkPrompt.attemptedProvider === "microsoft" ? "Microsoft" : "Google"} could not sign in
                {linkPrompt.email ? ` (${linkPrompt.email})` : ""} because this email already uses{" "}
                <strong>{formatExistingProviders(linkPrompt.methods)}</strong>. Sign in below with that method
                first — we will attach {linkPrompt.attemptedProvider === "microsoft" ? "Microsoft" : "Google"} so you can use either next time.
              </p>
              <button
                type="button"
                onClick={() => {
                  pendingLinkCredRef.current = null;
                  setLinkPrompt(null);
                }}
                style={{
                  fontSize: 11, fontWeight: 700, color: "#93C5FD", background: "transparent",
                  border: "1px solid rgba(147,197,253,.35)", borderRadius: 8, padding: "6px 12px", cursor: "pointer", fontFamily: "inherit",
                }}
              >
                Cancel linking
              </button>
            </div>
          )}

          {error && (
            <div style={{
              background: "rgba(239,68,68,.12)", border: "1px solid rgba(239,68,68,.25)",
              borderRadius: 10, padding: "10px 14px", color: "#F87171",
              fontSize: 12, marginBottom: 16, display: "flex", gap: 6, alignItems: "center",
            }}>
              ⚠️ {error}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            {isSignUp && (
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: sub, marginBottom: 6 }}>
                  Full Name
                </label>
                <input
                  type="text"
                  placeholder="Jane Doe"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  autoComplete="name"
                  style={{
                    width: "100%", padding: "11px 14px", borderRadius: 10,
                    border: `1.5px solid ${inpBorder}`, background: inp,
                    color: txt, fontSize: 13, outline: "none",
                    fontFamily: "inherit", transition: "border .2s", boxSizing: "border-box",
                  }}
                  onFocus={(e) => (e.target.style.borderColor = "var(--accent)")}
                  onBlur={(e) => (e.target.style.borderColor = inpBorder)}
                />
              </div>
            )}

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: sub, marginBottom: 6 }}>
                Email
              </label>
              <input
                type="email"
                placeholder={`name@${ORG_DOMAIN}`}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                style={{
                  width: "100%", padding: "11px 14px", borderRadius: 10,
                  border: `1.5px solid ${inpBorder}`, background: inp,
                  color: txt, fontSize: 13, outline: "none",
                  fontFamily: "inherit", transition: "border .2s", boxSizing: "border-box",
                }}
                onFocus={(e) => (e.target.style.borderColor = "var(--accent)")}
                onBlur={(e) => (e.target.style.borderColor = inpBorder)}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <label style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: sub }}>
                  Password
                </label>
                <button
                  type="button" onClick={() => setShowPass((p) => !p)}
                  style={{ fontSize: 10, color: "var(--accent)", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit" }}
                >
                  {showPass ? "Hide" : "Show"}
                </button>
              </div>
              <input
                type={showPass ? "text" : "password"}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={isSignUp ? "new-password" : "current-password"}
                style={{
                  width: "100%", padding: "11px 14px", borderRadius: 10,
                  border: `1.5px solid ${inpBorder}`, background: inp,
                  color: txt, fontSize: 13, outline: "none",
                  fontFamily: "inherit", transition: "border .2s", boxSizing: "border-box",
                }}
                onFocus={(e) => (e.target.style.borderColor = "var(--accent)")}
                onBlur={(e) => (e.target.style.borderColor = inpBorder)}
              />
            </div>

            {isSignUp && (
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: sub, marginBottom: 6 }}>
                  Confirm Password
                </label>
                <input
                  type={showPass ? "text" : "password"}
                  placeholder="Re-enter password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                  style={{
                    width: "100%", padding: "11px 14px", borderRadius: 10,
                    border: `1.5px solid ${inpBorder}`, background: inp,
                    color: txt, fontSize: 13, outline: "none",
                    fontFamily: "inherit", transition: "border .2s", boxSizing: "border-box",
                  }}
                  onFocus={(e) => (e.target.style.borderColor = "var(--accent)")}
                  onBlur={(e) => (e.target.style.borderColor = inpBorder)}
                />
              </div>
            )}

            {!isSignUp && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12, color: sub, cursor: "pointer" }}>
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} style={{ accentColor: "var(--accent)" }} />
                  Remember me
                </label>
                <button
                  type="button"
                  onClick={handleForgotPassword}
                  style={{ fontSize: 12, color: "var(--accent)", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit", fontWeight: 600 }}
                >
                  Forgot password?
                </button>
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              style={{
                width: "100%", padding: 13, borderRadius: 12, border: "none",
                cursor: busy ? "not-allowed" : "pointer",
                background: "linear-gradient(135deg,var(--accent),var(--accent2),var(--sky))",
                color: "white", fontWeight: 800, fontSize: 14,
                fontFamily: "inherit", opacity: busy ? 0.7 : 1,
                transition: "opacity .2s, transform .15s",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              }}
              onMouseEnter={(e) => { if (!busy) e.currentTarget.style.transform = "translateY(-1px)"; }}
              onMouseLeave={(e) => (e.currentTarget.style.transform = "translateY(0)")}
            >
              {loading ? (
                <>
                  <div style={{
                    width: 16, height: 16, borderRadius: "50%",
                    border: "2px solid rgba(255,255,255,.3)", borderTopColor: "white",
                    animation: "spin 1s linear infinite",
                  }} />
                  {isSignUp ? "Creating account…" : "Loading…"}
                </>
              ) : isSignUp ? "Create account" : "Sign in"}
            </button>

            <div style={{ textAlign: "center", marginTop: 14, fontSize: 12, color: sub }}>
              {isSignUp ? "Already have an account? " : "Don't have an account? "}
              <button
                type="button"
                onClick={() => resetForm(!isSignUp)}
                style={{
                  background: "none", border: "none", color: "var(--p2)", fontWeight: 700,
                  cursor: "pointer", fontFamily: "inherit", fontSize: 12, padding: 0,
                }}
              >
                {isSignUp ? "Sign in" : "Sign up"}
              </button>
            </div>
          </form>

          {isFirebaseConfigured && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 22, marginBottom: 4 }}>
                <div style={{ flex: 1, height: 1, background: cardBorder }} />
                <span style={{ fontSize: 11, color: sub, fontWeight: 600 }}>or</span>
                <div style={{ flex: 1, height: 1, background: cardBorder }} />
              </div>
            </>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
            <button
              type="button"
              disabled={busy}
              onClick={handleGoogle}
              style={{
                width: "100%",
                padding: 12,
                borderRadius: 12,
                border: `1.5px solid ${inpBorder}`,
                background: inp,
                color: txt,
                fontWeight: 700,
                fontSize: 13,
                fontFamily: "inherit",
                cursor: busy ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 10,
                opacity: busy ? 0.65 : 1,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
                <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6C44.21 37.2 46.98 31.49 46.98 24.55z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
              </svg>
              {googleLoading ? "Opening Google…" : "Continue with Google"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={handleMicrosoft}
              style={{
                width: "100%",
                padding: 12,
                borderRadius: 12,
                border: `1.5px solid ${inpBorder}`,
                background: inp,
                color: txt,
                fontWeight: 700,
                fontSize: 13,
                fontFamily: "inherit",
                cursor: busy ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 10,
                opacity: busy ? 0.65 : 1,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden>
                <rect width="10" height="10" x="1" y="1" fill="#f25022" />
                <rect width="10" height="10" x="11" y="1" fill="#7fba00" />
                <rect width="10" height="10" x="1" y="11" fill="#00a4ef" />
                <rect width="10" height="10" x="11" y="11" fill="#ffb900" />
              </svg>
              {microsoftLoading ? "Opening Microsoft…" : "Continue with Microsoft"}
            </button>
          </div>

          <div style={{ textAlign: "center", marginTop: 20, fontSize: 11, color: sub, lineHeight: 1.5 }}>
            <strong>Firebase Auth</strong> — email/password, Google, and Microsoft. Enable Email/Password in the Firebase console. Only @{ORG_DOMAIN} accounts are accepted.
          </div>
        </div>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&display=swap');
        @keyframes fadeUp { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
        @keyframes spin   { to { transform:rotate(360deg); } }
      `}</style>
    </div>
  );
}

export default function LoginWithTheme({ onLogin, theme }) {
  return <LoginPage onLogin={onLogin} theme={theme} />;
}
