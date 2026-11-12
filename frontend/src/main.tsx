import "./styles/tokens.css";
import "./styles/base.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { ApiProvider } from "./app/ApiContext";
import { AppRouter } from "./app/AppRouter";
import { createClient } from "./lib/api/client";

const root = document.getElementById("root");
if (root === null) throw new Error("Missing #root element");

const client = createClient({ fetch: window.fetch.bind(window) });

createRoot(root).render(
  <StrictMode>
    <ApiProvider client={client}>
      <BrowserRouter>
        <AppRouter />
      </BrowserRouter>
    </ApiProvider>
  </StrictMode>,
);
