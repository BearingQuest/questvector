# 0029. The desktop window renders data as text, sets a strict CSP, and checks bundle names

- **Status:** Accepted
- **Date:** 2026-11-26

## Context
Owner decision, 26 Nov 2026: fix this before backlog item 1 part 2 and v1.2.0. Reading `main` at 23e4775 found three gaps:

- **HTML from data.** `questvector/desktop/web/app.js` built HTML with `innerHTML` and template literals from unescaped values: dossier domains, text and headings (Dossier tab), bridge error messages, and the category names, gap keywords and red-flag phrases from the mission template (Sync-AST tab). Dossier files and mission templates are files in the workspace folder, and `CONTRIBUTING_TEMPLATES.md` invites templates from other people. A template with HTML in a category name would have run script in the pywebview window, which could send the text on screen to any website (against [ADR-0001](0001-local-only-distribution.md)) and call the `js_api` bridge.
- **No CSP.** `index.html` set no Content-Security-Policy, so nothing limited what such a script could do. (Backlog item 15 already asked for one, as risk-trainer has; [ADR-0016](0016-browser-app-static-pages.md) records the browser app's CSP.)
- **Unchecked bundle names.** `Api.export_bundle` and `qv export --bundle` built `bundles/<name>.<fmt>` from the name as given, so `../x` wrote outside `bundles/`. On the CLI the name is the user's own input; on the bridge it comes from the page.

Options considered for the first gap: escape each value before `innerHTML`, or never use markup APIs. Escaping has to be remembered at every call site; text-only has no such site.

## Decision
- **Text only.** Every value reaches the page through `textContent` or elements built with `document.createElement` and `replaceChildren()` (small helpers at the top of `app.js`). `app.js` uses no `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write`, including for static markup, so a test can forbid them outright. The page looks and behaves the same.
- **CSP as a `<meta>` tag** in `index.html`: `default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'`. The page has no inline script, `<style>`, `style=` attribute or `on…=` handler, and `style.css` has no `url()` or `@import`, so only one loosening was needed (`'unsafe-eval'`, below). `el.style.x = …` in `app.js` sets styles through the DOM, which `style-src 'self'` allows. `img-src` and `font-src` are unused today and kept for the redesign.
- **One bundle-name check**, `resolve_bundle_path` in `questvector/core/exporter.py`, used by the bridge and the CLI before anything else happens (on the CLI, before any narrative network call): the name must fully match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`, must not be `.` or `..`, and the resolved path must stay inside `bundles/` (`Path.is_relative_to`, so a link in `bundles/` that points elsewhere is refused). A bad name raises `ExportError`; the bridge returns its usual error envelope.
- Tests: `tests/test_desktop_web.py` (exact CSP, no inline code, no markup APIs in `app.js`), plus bad-name cases in `test_exporter.py`, `test_desktop_api.py` and `test_cli.py`. I checked by hand that each fix is guarded: putting `innerHTML` back, dropping `connect-src 'none'`, or removing the path check each fails a test.

## Consequences
- **Closed:** a hostile template or dossier can no longer run script in the window, and a bundle name can no longer write outside `bundles/`.
- **The `'unsafe-eval'` exception.** The first version of this CSP had `script-src 'self'` and was expected to keep the bridge working, from reading the pywebview 6.2.1 source. The owner's manual check on 26 Nov 2026 showed it didn't: every action returned "Desktop bridge is not ready yet." pywebview's injected `finish.js` first calls `window.pywebview._createApi(...)`, and `webview/js/api.js` (line 75) builds every `js_api` function with `new Function(...)`. Without `'unsafe-eval'` that throws, and `pywebviewready` (dispatched right after, in `finish.js`) never fires. The source reading missed `new Function`. So `script-src` is `'self' 'unsafe-eval'`, and nothing else in the CSP changed.
  - **Cost:** a script already running in the page can evaluate strings. Inline scripts and `on…=` handlers stay blocked (there is no `'unsafe-inline'`), and `connect-src 'none'` still stops a script sending data out, so the ADR-0001 exfiltration path stays closed. Text-only rendering is still the primary fix; the CSP is the second layer.
  - **Revisit** when pywebview no longer builds its bridge with `new Function`.
- **What else pywebview does under this CSP (from source; the manual check is the proof):** `app.py` passes a local path, so pywebview serves the folder from its own `http://127.0.0.1:<port>/`, which `'self'` matches. On macOS the bridge is `window.webkit.messageHandlers.jsBridge.postMessage`, a WebKit message handler rather than a network request, and pywebview injects `window.pywebview` and returns results with `evaluateJavaScript`, which CSP does not govern. `webview/js/customize.js` (line 34) adds a `<style>` element to turn off text selection; `style-src 'self'` blocks it. That is cosmetic, and left as is. Windows (WebView2) and Linux use other bridge paths and are untested.
- **Limits:**
  - A `<meta>` CSP can't set `frame-ancestors` (or `sandbox`, or a report endpoint).
  - The CSP is a second layer; text-only rendering is the fix.
  - The `app.js` scan test is a text scan, so it is a guardrail against putting a markup API back, not proof that nothing unsafe is built another way.
  - The name check guards against path escape, not filesystem naming: Windows reserved names such as `CON` are not refused.
  - The local page server stays on `127.0.0.1`; this record doesn't change it.
- **Revisit:** the redesign (backlog item 15) keeps the CSP and the text-only rule; any new asset it adds (logos, fonts) is served from the same origin.
