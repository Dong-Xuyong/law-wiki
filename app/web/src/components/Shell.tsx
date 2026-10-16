import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { ThemeToggle } from "./ThemeToggle";

const BANNER =
  "Apenas casos fictícios ou decisões publicadas. Não introduza dados de processos reais (Recomendações do CSM, 8 de abril de 2026).";

const MARKER = "MINUTA NÃO ASSINADA — AUXÍLIO À INVESTIGAÇÃO JURÍDICA";

type ShellProps = {
  children: ReactNode;
  email?: string;
  mock?: boolean;
  onLogin?: () => void;
  onLogout?: () => void;
};

export function Shell({ children, email, mock, onLogin, onLogout }: ShellProps) {
  const { pathname } = useLocation();
  const casosCurrent =
    pathname === "/" || pathname.startsWith("/casos") || pathname.startsWith("/minutas");
  const pesquisaCurrent = pathname.startsWith("/pesquisa");

  return (
    <>
      <a className="skip-link" href="#conteudo">
        Saltar para o conteúdo
      </a>
      <div className="sticky-stack">
        <p className="banner">{BANNER}</p>
        <p className="unsigned">{MARKER}</p>
        <header className="site-header">
          <div className="header-inner">
            <Link to="/" className="brand">
              <span className="brand-mark" aria-hidden="true">
                M
              </span>
              Minutas
            </Link>
            <nav className="site-nav" aria-label="Principal">
              <Link to="/" aria-current={casosCurrent ? "page" : undefined}>
                Casos
              </Link>
              <Link to="/pesquisa" aria-current={pesquisaCurrent ? "page" : undefined}>
                Pesquisa
              </Link>
            </nav>
            <div className="header-tools">
              {mock && <span className="demo-pill">Demonstração</span>}
              {email && <span className="who">{email}</span>}
              <ThemeToggle />
              {onLogout && (
                <button type="button" className="secondary" onClick={onLogout}>
                  Sair
                </button>
              )}
              {onLogin && (
                <button type="button" onClick={onLogin}>
                  Entrar
                </button>
              )}
            </div>
          </div>
        </header>
      </div>
      <main id="conteudo" tabIndex={-1}>
        <div className="wrap">{children}</div>
      </main>
    </>
  );
}
