import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { Companion } from "./companion/Companion";
import "./index.css";

const isCompanion = window.location.pathname.replace(/\/+$/, "") === "/companion";

createRoot(document.getElementById("root")!).render(
  <StrictMode>{isCompanion ? <Companion /> : <App />}</StrictMode>,
);
