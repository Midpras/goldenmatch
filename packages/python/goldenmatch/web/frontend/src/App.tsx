import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { ApiError, api, onAuthExpired, setAuthToken } from "./lib/api";
import { router } from "./router";

const qc = new QueryClient();

type GateState = "checking" | "ready" | "sign-in" | "error";

function SignIn({
  error,
  onSubmit,
  onRetry,
}: {
  error: string | null;
  onSubmit: (token: string) => void;
  onRetry?: () => void;
}) {
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit(token);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-6 py-12">
      <section
        aria-labelledby="sign-in-title"
        className="w-full max-w-md border border-ink-200 bg-paper-50/90 p-8 shadow-sm"
      >
        <p className="eyebrow text-gold-600">GoldenMatch · Workbench</p>
        <h1 id="sign-in-title" className="display mt-3 text-3xl text-ink-800">
          Sign in to your project
        </h1>
        <p className="mt-3 text-sm leading-6 text-ink-500">
          Enter the web access token configured for this server.
        </p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <label htmlFor="web-token" className="block text-sm font-medium text-ink-700">
            Access token
          </label>
          <input
            id="web-token"
            name="token"
            type="password"
            autoComplete="off"
            autoFocus
            required
            value={token}
            onChange={(event) => setToken(event.target.value)}
            aria-describedby={error ? "sign-in-error" : undefined}
            className="w-full font-mono text-sm bg-paper-100 border border-ink-200 text-ink-800 rounded px-2 py-2 focus:outline-none focus:border-gold-400 focus:shadow-gold transition"
          />
          {error && (
            <p id="sign-in-error" role="alert" className="text-sm text-red-700">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="w-full border border-gold-500 bg-gold-500 px-4 py-2 text-sm font-medium text-ink-900 transition-colors hover:bg-gold-400 disabled:cursor-wait disabled:opacity-60"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
          {onRetry && (
            <button
              type="button"
              disabled={submitting}
              onClick={onRetry}
              className="w-full border border-ink-200 px-4 py-2 text-sm text-ink-600 hover:border-gold-400 hover:text-gold-700 disabled:opacity-60"
            >
              Retry connection
            </button>
          )}
        </form>
      </section>
    </main>
  );
}

export default function App() {
  const [gateState, setGateState] = useState<GateState>("checking");
  const [signInError, setSignInError] = useState<string | null>(null);
  const lastToken = useRef<string | null>(null);

  const verifyProject = useCallback(async (submittedToken: string | null) => {
    setGateState("checking");
    setSignInError(null);
    setAuthToken(submittedToken);
    try {
      await api.project();
      setGateState("ready");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        lastToken.current = null;
        setAuthToken(null);
        setGateState("sign-in");
        setSignInError(submittedToken ? "That access token was not accepted." : null);
        return;
      }
      setGateState("error");
      setSignInError(
        error instanceof Error
          ? `Could not reach the project: ${error.message}`
          : "Could not reach the project. Check the server connection and try again.",
      );
    }
  }, []);

  useEffect(() => {
    const unsubscribe = onAuthExpired(() => {
      lastToken.current = null;
      qc.clear();
      setSignInError("Your session is no longer authorized. Sign in again.");
      setGateState("sign-in");
    });
    void verifyProject(null);
    return unsubscribe;
  }, [verifyProject]);

  const signIn = useCallback(
    async (token: string) => {
      lastToken.current = token;
      await verifyProject(token);
    },
    [verifyProject],
  );

  const retryConnection = useCallback(() => {
    void verifyProject(lastToken.current);
  }, [verifyProject]);
  if (gateState === "checking") {
    return (
      <div className="min-h-screen flex items-center justify-center" role="status">
        <span className="text-sm text-ink-500">Connecting to GoldenMatch…</span>
      </div>
    );
  }

  if (gateState !== "ready") {
    return (
      <QueryClientProvider client={qc}>
        <SignIn
          error={signInError}
          onSubmit={signIn}
          onRetry={gateState === "error" ? retryConnection : undefined}
        />
      </QueryClientProvider>
    );
  }

  return (
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
