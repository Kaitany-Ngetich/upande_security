import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App";
import { markPainted } from "./lib/splash";

const el = document.getElementById("security-root");
if (el) {
  createRoot(el).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  // After the first paint, not before it: uncovering on the render call itself
  // shows a root React has been handed but has not yet drawn, which is the
  // blank frame the cover exists to hide. The cover decides the rest — it also
  // waits out a one-second floor and any data still in flight.
  requestAnimationFrame(() => requestAnimationFrame(markPainted));
}
