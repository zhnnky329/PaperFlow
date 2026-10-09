import { StrictMode, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { App } from "./App";
const PdfReader = lazy(() =>
  import("./PdfReader").then((module) => ({ default: module.PdfReader })),
);
import "./styles.css";
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/settings" element={<App settingsPage />} />
        <Route
          path="/papers/:id/pdf"
          element={
            <Suspense
              fallback={<div className="empty">正在加载 PDF 阅读器…</div>}
            >
              <PdfReader />
            </Suspense>
          }
        />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
