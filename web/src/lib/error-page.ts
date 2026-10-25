/**
 * The page the server answers when it cannot render one (src/server.ts), in the reader's language (plan UX, A1,
 * defect F08: it was English only). Self-contained on purpose: it shows when the app itself could not run.
 */
import type { Locale } from "./i18n/catalogs";

const TEXT: Record<Locale, { title: string; body: string; retry: string; home: string }> = {
  es: {
    title: "Esta página no se ha podido cargar",
    body: "Algo ha fallado de nuestro lado. Puedes reintentar o volver al inicio.",
    retry: "Reintentar",
    home: "Ir al inicio",
  },
  en: {
    title: "This page didn't load",
    body: "Something went wrong on our end. You can try refreshing or head back home.",
    retry: "Try again",
    home: "Go home",
  },
};

export function renderErrorPage(locale: Locale = "es"): string {
  const t = TEXT[locale];
  return `<!doctype html>
<html lang="${locale}">
  <head>
    <meta charset="utf-8" />
    <title>${t.title} · PrediGol</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body { font: 15px/1.5 system-ui, -apple-system, sans-serif; background: #0d1512; color: #e8efe9; display: grid; place-items: center; min-height: 100vh; margin: 0; padding: 1.5rem; }
      .card { max-width: 28rem; width: 100%; text-align: center; padding: 2rem; }
      h1 { font-size: 1.25rem; margin: 0 0 0.5rem; }
      p { color: #a3b3a8; margin: 0 0 1.5rem; }
      .actions { display: flex; gap: 0.5rem; justify-content: center; flex-wrap: wrap; }
      a, button { min-height: 44px; padding: 0.5rem 1rem; border-radius: 0.375rem; font: inherit; cursor: pointer; text-decoration: none; border: 1px solid transparent; box-sizing: border-box; display: inline-flex; align-items: center; }
      .primary { background: #e8efe9; color: #0d1512; }
      .secondary { background: transparent; color: #e8efe9; border-color: #3a4a40; }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>${t.title}</h1>
      <p>${t.body}</p>
      <div class="actions">
        <button class="primary" onclick="location.reload()">${t.retry}</button>
        <a class="secondary" href="/">${t.home}</a>
      </div>
    </div>
  </body>
</html>`;
}
