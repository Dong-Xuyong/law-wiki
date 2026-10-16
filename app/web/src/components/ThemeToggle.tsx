import { useEffect, useState } from "react";

const STORAGE_KEY = "minutas-theme";

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(value: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Private mode can block storage. The class on <html> still switches for this visit.
  }
}

export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applySystem = () => {
      if (readStored()) return;
      document.documentElement.classList.toggle("dark", media.matches);
      setDark(media.matches);
    };
    applySystem();
    media.addEventListener("change", applySystem);
    return () => media.removeEventListener("change", applySystem);
  }, []);

  function toggle() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    writeStored(next ? "dark" : "light");
    setDark(next);
  }

  return (
    <button
      type="button"
      className="dong-theme-toggle"
      onClick={toggle}
      aria-pressed={dark}
      aria-label={dark ? "Ativar tema claro" : "Ativar tema escuro"}
    >
      <span className="dong-theme-toggle__track" aria-hidden="true">
        <span className="dong-theme-toggle__icon">☀</span>
        <span className="dong-theme-toggle__knob" />
        <span className="dong-theme-toggle__icon">☾</span>
      </span>
    </button>
  );
}
