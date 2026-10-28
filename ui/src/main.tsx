import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyTheme, loadTheme } from "./theme";
import "./theme/light.css";
import "./theme/light-mc.css";
import "./theme/light-hc.css";
import "./theme/dark.css";
import "./theme/dark-mc.css";
import "./theme/dark-hc.css";
import "./styles.css";

applyTheme(loadTheme());  // before the first paint, so the page never flashes the wrong scheme

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
