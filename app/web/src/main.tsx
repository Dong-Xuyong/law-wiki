import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/dong-ui-theme.css";
import "./styles/app.css";

const root = document.getElementById("root");
if (!root) throw new Error("Elemento #root em falta.");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
