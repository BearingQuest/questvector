// QuestVector Tactical Flight Deck — front-end logic.
// Every data call goes through window.pywebview.api (see
// questvector/desktop/app.py::Api), which always resolves to
// {ok: true, data: ...} or {ok: false, error: "..."} — never a raw
// exception — so every handler below only needs one shape to branch on.

const GAUGE_CIRCUMFERENCE = 282.6;

let apiReady = false;
let lastScan = { jdText: "", templateId: "" };
let llmProviders = [];

function setStatus(text, tone = "success") {
  const el = document.getElementById("status-line");
  el.textContent = text;
  el.style.color = tone === "critical" ? "var(--lock-on-red)"
    : tone === "warning" ? "var(--afterburner-amber)"
    : tone === "low_relevance" ? "var(--hud-text-dim)"
    : "var(--tactical-green)";
  el.style.borderColor = el.style.color;
}

function currentWorkspaceDir() {
  return document.getElementById("workspace-dir").value.trim();
}

function requireApi() {
  if (!apiReady || !window.pywebview) {
    setStatus("BRIDGE OFFLINE", "critical");
    throw new Error("Desktop bridge is not ready yet.");
  }
  return window.pywebview.api;
}

function renderJson(elementId, payload) {
  document.getElementById(elementId).textContent = JSON.stringify(payload, null, 2);
}

// Data from dossiers, templates and bridge errors reaches the page only
// through these helpers (createElement + textContent), never as markup.
function el(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

function setList(list, items) {
  list.replaceChildren(...items.map((text) => el("li", text)));
}

function listItem(label, text) {
  const li = el("li");
  li.append(el("b", label));
  if (text !== undefined) li.append(`: ${text}`);
  return li;
}

function section(title, count, items) {
  const wrapper = el("div");
  const list = el("ul");
  list.className = "hud-list";
  list.replaceChildren(...items);
  wrapper.append(el("h3", `${title} (${count})`), list);
  return wrapper;
}

function setOptions(select, placeholder, options) {
  const first = el("option", placeholder);
  first.value = "";
  select.replaceChildren(first, ...options);
}

// --- Tab switching -----------------------------------------------------

document.getElementById("tabs").addEventListener("click", (event) => {
  const button = event.target.closest(".hud-tab");
  if (!button) return;
  document.querySelectorAll(".hud-tab").forEach((tab) => tab.classList.remove("active"));
  button.classList.add("active");
  document.querySelectorAll("[data-panel]").forEach((panel) => panel.classList.add("hidden"));
  document.getElementById(`panel-${button.dataset.tab}`).classList.remove("hidden");
  if (button.dataset.tab === "sync") refreshTemplates();
  if (button.dataset.tab === "vault" && llmProviders.length === 0) loadLlmProviders();
});

// --- Workspace -----------------------------------------------------------

document.getElementById("btn-launch").addEventListener("click", async () => {
  try {
    const api = requireApi();
    const dir = currentWorkspaceDir();
    if (!dir) return setStatus("ENTER A WORKSPACE PATH", "warning");
    const response = await api.launch_workspace(dir);
    renderJson("workspace-output", response);
    setStatus(response.ok ? "WORKSPACE READY" : "LAUNCH FAILED", response.ok ? "success" : "critical");
  } catch (err) {
    renderJson("workspace-output", { ok: false, error: String(err) });
  }
});

// --- Dossier -------------------------------------------------------------

document.getElementById("btn-load-dossier").addEventListener("click", async () => {
  const api = requireApi();
  const dir = currentWorkspaceDir();
  if (!dir) return setStatus("ENTER A WORKSPACE PATH", "warning");
  const response = await api.get_dossier(dir);
  const container = document.getElementById("dossier-output");
  container.replaceChildren();
  if (!response.ok) {
    container.textContent = response.error;
    return;
  }
  const { capabilities, chronology, impact } = response.data;
  container.replaceChildren(
    section("Capabilities", capabilities.length, capabilities.map((c) => listItem(c.domain, c.text))),
    section("Chronology", chronology.length, chronology.map((e) => listItem(e.heading))),
    section("Impact", impact.length, impact.map((s) => listItem(s.heading))),
  );
});

// --- Sync-AST / G-Force gauge ---------------------------------------------

async function refreshTemplates() {
  const api = requireApi();
  const dir = currentWorkspaceDir();
  const select = document.getElementById("template-select");
  const placeholder = "Select mission template…";
  setOptions(select, placeholder, []);
  if (!dir) return;
  const response = await api.list_templates(dir);
  if (!response.ok) return;
  setOptions(select, placeholder, response.data.map((template) => {
    const option = el("option", `${template.title} (${template.id})`);
    option.value = template.id;
    return option;
  }));
}

document.getElementById("btn-refresh-templates").addEventListener("click", refreshTemplates);

// coverage is null when the posting asks nothing of the template: no number, never 100.
function setGauge(coverage, alertLevel) {
  const fill = document.getElementById("gauge-fill");
  const shown = coverage === null ? 0 : coverage;
  const offset = GAUGE_CIRCUMFERENCE * (1 - Math.max(0, Math.min(100, shown)) / 100);
  fill.style.strokeDashoffset = String(offset);
  // At 0 the round line cap would still draw a dot, at the far (100%) end of the arc: hide the fill.
  fill.style.display = shown <= 0 ? "none" : "";
  const colorVar = alertLevel === "critical" ? "var(--lock-on-red)"
    : alertLevel === "warning" ? "var(--afterburner-amber)"
    : alertLevel === "low_relevance" ? "var(--hud-text-dim)"
    : "var(--tactical-green)";
  fill.style.stroke = colorVar;
  document.getElementById("gauge-readout").textContent =
    coverage === null ? "--" : `${coverage.toFixed(1)}%`;
  document.getElementById("gauge-alert").textContent =
    alertLevel === "critical" ? "CRITICAL GAP DETECTED"
    : alertLevel === "warning" ? "GAPS DETECTED"
    : alertLevel === "low_relevance" ? "LOW RELEVANCE"
    : "G-FORCE MATCH LOCKED";
}

document.getElementById("btn-run-scan").addEventListener("click", async () => {
  const api = requireApi();
  const dir = currentWorkspaceDir();
  const templateId = document.getElementById("template-select").value;
  const jdText = document.getElementById("jd-text").value;
  if (!dir || !templateId || !jdText.trim()) {
    return setStatus("WORKSPACE, TEMPLATE, AND JD TEXT REQUIRED", "warning");
  }
  setStatus("SCANNING", "warning");
  const response = await api.sync_ast(dir, jdText, templateId);
  if (!response.ok) {
    setStatus("SCAN FAILED", "critical");
    setList(document.getElementById("category-list"), [response.error]);
    return;
  }
  lastScan = { jdText, templateId };
  const result = response.data;
  // A low-relevance result is not scored: no number on the gauge (coverage stays in the data).
  setGauge(result.low_relevance ? null : result.coverage, result.alert_level);
  document.getElementById("gauge-relevance").textContent = `Relevance: ${result.relevance_text}`;
  document.getElementById("gauge-counts").textContent = result.counts_text;
  document.getElementById("relevance-note").textContent = result.relevance_note;
  setStatus("SCAN COMPLETE", result.alert_level);

  setList(
    document.getElementById("category-list"),
    result.categories.map((c, i) => {
      const shown = result.category_coverage_texts[i];
      const detail = shown === "-" ? "no coverage figure" : shown;
      return `${c.name}: ${detail} (weight ${c.weight.toFixed(2)}), ${c.counts_text}`;
    }),
  );
  setList(document.getElementById("gaps-list"), result.gaps.length ? result.gaps : ["None"]);
  setList(
    document.getElementById("weak-categories-list"),
    result.weak_categories.length ? result.weak_categories : ["None"],
  );
  setList(
    document.getElementById("negation-list"),
    result.negation_warnings.length
      ? result.negation_warnings.map((w) => `${w.file} > ${w.heading}: "${w.line}" (${w.keywords.join(", ")})`)
      : ["None"],
  );
  setList(document.getElementById("red-flags-list"), result.red_flags.length ? result.red_flags : ["None"]);
});

// --- Templates -------------------------------------------------------------

document.getElementById("btn-validate-template").addEventListener("click", async () => {
  const api = requireApi();
  const path = document.getElementById("template-path").value.trim();
  const fix = document.getElementById("template-fix").checked;
  if (!path) return setStatus("ENTER A TEMPLATE PATH", "warning");
  const response = await api.validate_template(path, fix);
  renderJson("template-output", response);
  setStatus(response.ok && response.data.valid ? "TEMPLATE VALID" : "TEMPLATE INVALID",
    response.ok && response.data.valid ? "success" : "warning");
});

// --- Export ------------------------------------------------------------

document.getElementById("btn-export").addEventListener("click", async () => {
  const api = requireApi();
  const dir = currentWorkspaceDir();
  const name = document.getElementById("export-name").value.trim();
  const fmt = document.getElementById("export-format").value;
  const style = document.getElementById("export-style").value;
  const cutoffYears = document.getElementById("export-cutoff").checked ? 20 : null;
  if (!dir || !name) return setStatus("WORKSPACE AND BUNDLE NAME REQUIRED", "warning");
  if (cutoffYears !== null && style !== "resume") {
    return setStatus("THE CUTOFF NEEDS THE RESUME STYLE", "warning");
  }
  const response = await api.export_bundle(
    dir, name, fmt, lastScan.jdText, lastScan.templateId, style, cutoffYears);
  renderJson("export-output", response);
  const check = response.ok ? response.data.check : null;
  const notes = response.ok && response.data.notes ? response.data.notes : [];
  setList(document.getElementById("export-notes"), check ? [...notes, ...check.lines] : notes);
  if (response.ok && check && !check.passed) {
    return setStatus("BUNDLE EXPORTED, FILE CHECK FAILED", "warning");
  }
  setStatus(response.ok ? "BUNDLE EXPORTED" : "EXPORT FAILED", response.ok ? "success" : "critical");
});

// --- Vault ---------------------------------------------------------------

async function loadLlmProviders() {
  const api = requireApi();
  const response = await api.list_llm_providers();
  if (!response.ok) return;
  llmProviders = response.data.providers;
  const select = document.getElementById("vault-provider");
  setOptions(select, "Select LLM provider…", llmProviders.map((provider) => {
    const option = el("option", provider.is_local ? `${provider.display_name} (local)` : provider.display_name);
    option.value = provider.id;
    return option;
  }));
}

function updateProviderNote() {
  const providerId = document.getElementById("vault-provider").value;
  const provider = llmProviders.find((p) => p.id === providerId);
  const note = document.getElementById("vault-provider-note");
  const apiKeyInput = document.getElementById("vault-api-key");
  if (!provider) {
    note.textContent = "";
    apiKeyInput.disabled = false;
    return;
  }
  const setupLink = provider.api_key_setup_url
    ? (provider.requires_api_key ? `Get a key: ${provider.api_key_setup_url}` : `Install: ${provider.api_key_setup_url}`)
    : "";
  note.textContent = [provider.setup_note, setupLink].filter(Boolean).join(" ");
  apiKeyInput.disabled = !provider.requires_api_key;
  apiKeyInput.placeholder = provider.requires_api_key
    ? `${provider.display_name} API key`
    : "Not needed for this provider";
}

document.getElementById("vault-provider").addEventListener("change", updateProviderNote);

document.getElementById("btn-set-key").addEventListener("click", async () => {
  const api = requireApi();
  const dir = currentWorkspaceDir();
  const providerId = document.getElementById("vault-provider").value;
  const provider = llmProviders.find((p) => p.id === providerId);
  const passphrase = document.getElementById("vault-passphrase").value;
  const apiKey = document.getElementById("vault-api-key").value;
  const model = document.getElementById("vault-model").value.trim();
  if (!dir || !providerId || !passphrase) return setStatus("DIR, PROVIDER, AND PASSPHRASE REQUIRED", "warning");
  if (provider && provider.requires_api_key && !apiKey) return setStatus("THIS PROVIDER REQUIRES AN API KEY", "warning");
  const response = await api.set_llm_key(dir, passphrase, providerId, apiKey, model, "");
  renderJson("vault-output", response);
  setStatus(response.ok ? "PROVIDER STORED" : "VAULT ERROR", response.ok ? "success" : "critical");
});

// What the output check stripped and flagged (ADR-0032). Flags are for review only;
// they are never part of an export. Shown as text, like everything else (ADR-0029).
function renderNarrativeChecks(data) {
  const removed = data.removed || [];
  const flags = data.flags || [];
  document.getElementById("narrative-removed-heading").textContent = removed.length
    ? `Removed from the summary (not exported): ${removed.length}` : "";
  setList(document.getElementById("narrative-removed"), removed);
  document.getElementById("narrative-flags-heading").textContent = flags.length
    ? `Review these sentences (they are not blocked): ${flags.length}` : "";
  setList(document.getElementById("narrative-flags"), flags.map(
    (flag) => `${flag.terms.join(", ")} (${flag.kind.replace("_", " ")}): ${flag.sentence}`));
}

document.getElementById("btn-generate-narrative").addEventListener("click", async () => {
  const api = requireApi();
  const dir = currentWorkspaceDir();
  const passphrase = document.getElementById("vault-passphrase").value;
  if (!dir || !passphrase || !lastScan.jdText) {
    return setStatus("RUN A SCAN AND ENTER PASSPHRASE FIRST", "warning");
  }
  setStatus("CONTACTING LLM (NETWORK CALL)", "warning");
  const response = await api.generate_narrative(dir, lastScan.jdText, passphrase);
  renderJson("vault-output", response);
  renderNarrativeChecks(response.ok ? response.data : { removed: [], flags: [] });
  setStatus(response.ok ? "NARRATIVE GENERATED" : "NARRATIVE FAILED", response.ok ? "success" : "critical");
});

// --- Bridge readiness ------------------------------------------------------

window.addEventListener("pywebviewready", () => {
  apiReady = true;
  setStatus("FLIGHT DECK ONLINE");
});

// Fallback for environments where the event fires before this script binds.
if (window.pywebview && window.pywebview.api) {
  apiReady = true;
  setStatus("FLIGHT DECK ONLINE");
}
