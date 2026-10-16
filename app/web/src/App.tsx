import { useCallback, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { createHttpApi } from "./api/http";
import { createMockApi } from "./api/mock";
import { ApiProvider } from "./api/context";
import { Shell } from "./components/Shell";
import { completeSignIn, createUserManager, idToken, logout, readAuthError } from "./auth";
import { isMockConfig, loadConfig } from "./config";
import { messageOf } from "./lib/messages";
import { CasePage } from "./pages/CasePage";
import { CasesPage } from "./pages/CasesPage";
import { DraftPage } from "./pages/DraftPage";
import { LoginPage } from "./pages/LoginPage";
import { SearchPage } from "./pages/SearchPage";
import type { AppConfig } from "./types";

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<CasesPage />} />
      <Route path="/casos/:caseId" element={<CasePage />} />
      <Route path="/minutas/:draftId" element={<DraftPage />} />
      <Route path="/pesquisa" element={<SearchPage />} />
      <Route
        path="*"
        element={
          <>
            <h1>Página não encontrada</h1>
            <p>Este endereço não corresponde a nenhum ecrã do Minutas.</p>
          </>
        }
      />
    </Routes>
  );
}

function MockSession() {
  const api = useMemo(() => createMockApi(), []);
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let stop = false;
    void api.me().then((me) => {
      if (!stop) setEmail(me.email);
    });
    return () => {
      stop = true;
    };
  }, [api]);

  return (
    <Shell
      email={email}
      mock
      onLogout={() => setNotice("Modo de demonstração: não há sessão para terminar.")}
    >
      {notice && (
        <p role="status" className="hint">
          {notice}
        </p>
      )}
      <ApiProvider api={api}>
        <AppRoutes />
      </ApiProvider>
    </Shell>
  );
}

function OidcSession({ config }: { config: AppConfig }) {
  const manager = useMemo(() => createUserManager(config), [config]);
  const getToken = useCallback(() => idToken(manager), [manager]);
  const api = useMemo(() => createHttpApi(config.apiBase, getToken), [config.apiBase, getToken]);
  const [phase, setPhase] = useState<"loading" | "in" | "out" | "error">("loading");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let stop = false;
    void (async () => {
      const authError = readAuthError();
      if (authError) {
        if (!stop) {
          setMessage(authError);
          setPhase("error");
        }
        return;
      }
      try {
        await completeSignIn(manager);
        const token = await idToken(manager);
        if (stop) return;
        if (!token) {
          setPhase("out");
          return;
        }
        try {
          const me = await api.me();
          if (!stop) setEmail(me.email);
        } catch {
          if (!stop) setEmail("");
        }
        if (!stop) setPhase("in");
      } catch (error) {
        if (!stop) {
          setMessage(messageOf(error));
          setPhase("error");
        }
      }
    })();
    return () => {
      stop = true;
    };
  }, [api, manager]);

  async function enter() {
    setMessage("");
    try {
      await manager.signinRedirect();
    } catch (error) {
      setMessage(messageOf(error));
      setPhase("error");
    }
  }

  async function leave() {
    try {
      await logout(config, manager);
    } catch (error) {
      setMessage(messageOf(error));
      setPhase("error");
    }
  }

  return (
    <Shell
      email={phase === "in" ? email : undefined}
      onLogin={phase === "out" || phase === "error" ? () => void enter() : undefined}
      onLogout={phase === "in" ? () => void leave() : undefined}
    >
      {phase === "loading" && <p role="status">A carregar a sessão…</p>}
      {phase === "error" && (
        <>
          <p role="alert" className="alert">
            {message || "A autenticação falhou."}
          </p>
          <LoginPage onLogin={() => void enter()} />
        </>
      )}
      {phase === "out" && <LoginPage onLogin={() => void enter()} error={message} />}
      {phase === "in" && (
        <ApiProvider api={api}>
          <AppRoutes />
        </ApiProvider>
      )}
    </Shell>
  );
}

function Gate() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stop = false;
    void loadConfig()
      .then((next) => {
        if (!stop) setConfig(next);
      })
      .catch((loadError: unknown) => {
        if (!stop) setError(messageOf(loadError));
      });
    return () => {
      stop = true;
    };
  }, []);

  if (error) {
    return (
      <Shell>
        <p role="alert" className="alert">
          {error}
        </p>
      </Shell>
    );
  }
  if (!config) {
    return (
      <Shell>
        <p role="status">A carregar a configuração…</p>
      </Shell>
    );
  }
  if (isMockConfig(config)) return <MockSession />;
  return <OidcSession config={config} />;
}

export function App() {
  return (
    <BrowserRouter>
      <Gate />
    </BrowserRouter>
  );
}
