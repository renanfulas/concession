// Tela somente leitura do console (/team).
//
// Fala apenas com a API do console (/web/support/*), na mesma origem. A sessao
// vive no cookie HttpOnly emitido pela API; esta pagina nao guarda nada no
// armazenamento do navegador e nunca escreve telefone ou codigo em log.
// Toda regra (SLA, cor, ordenacao, filtro) vem da API: aqui so formatamos.
"use strict";

const API = {
  session: "/web/support/auth/session",
  start: "/web/support/auth/start",
  confirm: "/web/support/auth/confirm",
  logout: "/web/support/auth/logout",
  domains: "/web/support/domains",
  cases: "/web/support/cases",
};

const REFRESH_INTERVAL_MS = 60 * 1000;
const QUEUE_LIMIT = 100;
const TIME_ZONE = "America/Sao_Paulo";

const PRIORITY_LABELS = {
  urgent: "Urgente",
  high: "Alta",
  normal: "Normal",
  low: "Baixa",
};

const STATUS_LABELS = {
  open: "Aberto",
  in_progress: "Em atendimento",
  waiting_customer: "Aguardando cliente",
  pending_consent: "Aguardando consentimento",
  closed: "Fechado",
  cancelled: "Cancelado",
};

const LIGHT_LABELS = {
  red: "Vermelho · estourado",
  yellow: "Amarelo · atenção",
  green: "Verde · no prazo",
  paused: "Pausado",
};

const CHANNEL_LABELS = {
  whatsapp: "WhatsApp",
  web: "Web",
};

const dateTimeFormat = new Intl.DateTimeFormat("pt-BR", {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const clockFormat = new Intl.DateTimeFormat("pt-BR", {
  timeZone: TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
});

const state = {
  // Telefone so em memoria, entre o start e o confirm; limpo depois.
  phone: null,
  challengeId: null,
  hintName: null,
  domainNames: {},
  refreshTimer: null,
  loading: false,
  // Filtro trocado durante uma leitura: refaz a leitura ao terminar.
  pendingRefresh: false,
};

const el = (id) => document.getElementById(id);

const views = {
  loading: el("view-loading"),
  unavailable: el("view-unavailable"),
  login: el("view-login"),
  queue: el("view-queue"),
};

class ApiError extends Error {
  constructor(status, detail) {
    super(`api_error_${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function api(path, { method = "GET", body } = {}) {
  const headers = {
    Accept: "application/json",
    // Cabecalho anti-CSRF que a API do console exige nas escritas.
    "X-Requested-With": "XMLHttpRequest",
  };
  const init = { method, headers, credentials: "same-origin", cache: "no-store" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    throw new ApiError(0, "network_error");
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? payload.detail : null;
    const apiError = new ApiError(response.status, detail);
    apiError.payload = payload;
    apiError.retryAfter = response.headers.get("Retry-After");
    throw apiError;
  }
  return payload;
}

function showView(name) {
  for (const [key, node] of Object.entries(views)) {
    node.hidden = key !== name;
  }
  if (name !== "queue") {
    stopRefresh();
  }
}

function showUnavailable(error) {
  const detail = el("unavailable-detail");
  if (error && error.status === 404) {
    detail.textContent =
      "A API do console está desligada nesta instância (ENABLE_SUPPORT_CONSOLE).";
  } else if (error && error.status === 503) {
    detail.textContent =
      "O console está sem banco de dados no momento. Tente de novo em instantes.";
  } else if (error && error.status === 429) {
    detail.textContent = "Muitas leituras seguidas. Aguarde um minuto e tente de novo.";
  } else {
    detail.textContent =
      "A API do console não respondeu. Pode estar desligada nesta instância ou sem banco de dados.";
  }
  el("session-box").hidden = true;
  showView("unavailable");
}

// --------------------------------------------------------------------------
// Sessao e login (fluxo OTP staff existente)
// --------------------------------------------------------------------------

async function boot() {
  showView("loading");
  try {
    const session = await api(API.session);
    await enterQueue(session.display_name);
  } catch (error) {
    if (error.status === 401) {
      const hint = error.payload && error.payload.hint;
      showLogin(hint && hint.display_name ? hint.display_name : null);
      return;
    }
    showUnavailable(error);
  }
}

function showLogin(hintName) {
  state.hintName = hintName;
  state.phone = null;
  state.challengeId = null;
  el("session-box").hidden = true;
  el("code-form").hidden = true;
  el("code-input").value = "";
  hideLoginMessage();
  if (hintName) {
    el("hint-button").textContent = `Entrar como ${hintName}`;
    el("hint-box").hidden = false;
    el("phone-form").hidden = true;
  } else {
    el("hint-box").hidden = true;
    el("phone-form").hidden = false;
  }
  showView("login");
}

function setLoginMessage(text) {
  const node = el("login-message");
  node.textContent = text;
  node.hidden = false;
}

function hideLoginMessage() {
  const node = el("login-message");
  node.textContent = "";
  node.hidden = true;
}

function loginErrorText(error) {
  if (error.status === 422) {
    return "Número inválido. Use o formato internacional, por exemplo +5511900000000.";
  }
  if (error.status === 400) {
    return "Código inválido ou expirado. Peça um novo código.";
  }
  if (error.status === 429) {
    const wait = Number.parseInt(error.retryAfter || "", 10);
    return Number.isFinite(wait)
      ? `Muitas tentativas. Tente de novo em ${wait} segundos.`
      : "Muitas tentativas. Aguarde um pouco e tente de novo.";
  }
  return "";
}

async function startOtp(phone) {
  hideLoginMessage();
  try {
    const result = await api(API.start, {
      method: "POST",
      body: phone ? { phone } : {},
    });
    state.phone = phone;
    state.challengeId = result.challenge_id;
    el("phone-form").hidden = true;
    el("hint-box").hidden = true;
    el("code-form").hidden = false;
    el("code-input").focus();
  } catch (error) {
    const text = loginErrorText(error);
    if (text) {
      setLoginMessage(text);
      return;
    }
    showUnavailable(error);
  }
}

async function confirmOtp(code) {
  hideLoginMessage();
  const body = { challenge_id: state.challengeId, code };
  if (state.phone) {
    body.phone = state.phone;
  }
  try {
    const login = await api(API.confirm, { method: "POST", body });
    state.phone = null;
    state.challengeId = null;
    el("code-input").value = "";
    await enterQueue(login.display_name);
  } catch (error) {
    el("code-input").value = "";
    const text = loginErrorText(error);
    if (text) {
      setLoginMessage(text);
      return;
    }
    showUnavailable(error);
  }
}

function normalizePhoneInput(value) {
  // So formatacao de digitacao: a API valida o E.164 de verdade.
  return value.replace(/[\s().-]/g, "");
}

el("phone-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const phone = normalizePhoneInput(el("phone-input").value);
  if (!phone) {
    setLoginMessage("Informe o telefone cadastrado.");
    return;
  }
  el("phone-input").value = "";
  startOtp(phone);
});

el("hint-button").addEventListener("click", () => startOtp(null));

el("other-number-button").addEventListener("click", () => {
  el("hint-box").hidden = true;
  el("phone-form").hidden = false;
  el("phone-input").focus();
});

el("code-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const code = el("code-input").value.trim();
  if (code.length < 4) {
    setLoginMessage("Digite o código recebido.");
    return;
  }
  confirmOtp(code);
});

el("code-back").addEventListener("click", () => showLogin(state.hintName));

el("logout-button").addEventListener("click", async () => {
  try {
    await api(API.logout, { method: "POST" });
  } catch (error) {
    // A sessao expira sozinha no servidor; seguimos para a tela de login.
  }
  boot();
});

el("retry-button").addEventListener("click", () => boot());

// --------------------------------------------------------------------------
// Fila somente leitura
// --------------------------------------------------------------------------

async function enterQueue(displayName) {
  el("session-name").textContent = displayName ? `Olá, ${displayName}` : "";
  el("session-box").hidden = false;
  await loadDomains();
  showView("queue");
  await refreshQueue();
  startRefresh();
}

async function loadDomains() {
  try {
    const result = await api(API.domains);
    const select = el("filter-domain");
    const current = select.value;
    while (select.options.length > 1) {
      select.remove(1);
    }
    state.domainNames = {};
    for (const domain of result.domains || []) {
      state.domainNames[domain.name] = domain.display_name;
      const option = document.createElement("option");
      option.value = domain.name;
      option.textContent = domain.display_name;
      select.append(option);
    }
    select.value = current;
  } catch (error) {
    // Sem a lista, a fila ainda funciona e mostra o identificador do dominio.
    state.domainNames = {};
  }
}

function startRefresh() {
  stopRefresh();
  state.refreshTimer = window.setInterval(refreshQueue, REFRESH_INTERVAL_MS);
}

function stopRefresh() {
  if (state.refreshTimer !== null) {
    window.clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }
}

function buildCasesUrl() {
  const params = new URLSearchParams({
    view: "active",
    sort: "attention",
    limit: String(QUEUE_LIMIT),
  });
  const domain = el("filter-domain").value;
  const color = el("filter-color").value;
  if (domain) {
    params.set("domain", domain);
  }
  if (color) {
    params.set("color", color);
  }
  return `${API.cases}?${params.toString()}`;
}

async function refreshQueue() {
  if (state.loading) {
    state.pendingRefresh = true;
    return;
  }
  state.loading = true;
  state.pendingRefresh = false;
  try {
    const result = await api(buildCasesUrl());
    renderQueue(result);
    el("updated-at").textContent = `Atualizado às ${clockFormat.format(new Date())}`;
  } catch (error) {
    if (error.status === 401) {
      boot();
      return;
    }
    state.pendingRefresh = false;
    showUnavailable(error);
  } finally {
    state.loading = false;
  }
  if (state.pendingRefresh) {
    refreshQueue();
  }
}

function renderQueue(result) {
  const list = el("case-list");
  list.replaceChildren();
  const cases = Array.isArray(result.cases) ? result.cases : [];
  for (const item of cases) {
    list.append(renderCase(item));
  }
  el("queue-empty").hidden = cases.length > 0;

  const notices = [];
  if (result.truncated) {
    notices.push(
      "A fila ativa passou do limite de leitura do console; alguns casos mais novos não aparecem."
    );
  }
  if (cases.length >= QUEUE_LIMIT) {
    notices.push(`Mostrando os ${QUEUE_LIMIT} primeiros casos da ordem de atenção.`);
  }
  const notice = el("queue-notice");
  notice.textContent = notices.join(" ");
  notice.hidden = notices.length === 0;
}

function lightOf(sla) {
  if (!sla) {
    return null;
  }
  if (sla.paused) {
    return "paused";
  }
  return LIGHT_LABELS[sla.color] ? sla.color : null;
}

function formatDuration(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const days = Math.floor(minutes / (60 * 24));
  const hours = Math.floor((minutes % (60 * 24)) / 60);
  const rest = minutes % 60;
  if (days > 0) {
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }
  if (hours > 0) {
    return `${hours}h${String(rest).padStart(2, "0")}`;
  }
  return `${rest} min`;
}

function timeLeftText(sla) {
  if (!sla) {
    return "Sem prazo calculado";
  }
  if (sla.paused) {
    return "Prazo pausado";
  }
  const deadline = Date.parse(sla.deadline_at);
  if (Number.isNaN(deadline)) {
    return "";
  }
  const diffMinutes = (deadline - Date.now()) / 60000;
  if (diffMinutes >= 0) {
    return `Faltam ${formatDuration(diffMinutes)}`;
  }
  return `Estourado há ${formatDuration(-diffMinutes)}`;
}

function formatDateTime(value) {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : dateTimeFormat.format(parsed);
}

function textNode(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  node.textContent = text;
  return node;
}

function field(label, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  wrapper.append(textNode("dt", "", label), textNode("dd", "", value));
  return wrapper;
}

function renderCase(item) {
  const sla = item.sla || null;
  const light = lightOf(sla);
  const li = document.createElement("li");
  li.className = `case-card light-${light || "none"}`;

  const head = document.createElement("div");
  head.className = "case-head";

  const lightBadge = textNode(
    "span",
    `light-badge light-${light || "none"}`,
    light ? LIGHT_LABELS[light] : "Sem semáforo"
  );
  const dot = document.createElement("span");
  dot.className = "light-dot";
  dot.setAttribute("aria-hidden", "true");
  lightBadge.prepend(dot);

  const priority = textNode(
    "span",
    `priority priority-${item.priority}`,
    `Prioridade ${PRIORITY_LABELS[item.priority] || item.priority}`
  );
  const domainName = state.domainNames[item.domain] || item.domain;
  const domain = textNode("span", "domain", domainName);
  const reference = textNode("code", "case-ref", `#${String(item.case_id).slice(0, 8)}`);
  reference.title = "Referência do caso (início do identificador)";

  head.append(lightBadge, priority, domain, reference);

  const deadline = document.createElement("dl");
  deadline.className = "case-fields";
  deadline.append(
    field("Prazo", sla ? formatDateTime(sla.deadline_at) : "—"),
    field("Tempo", timeLeftText(sla)),
    field("Base do prazo", sla && sla.basis ? sla.basis : "SLA padrão do console"),
    field("Status", STATUS_LABELS[item.status] || item.status),
    field("Responsável", item.assignee ? item.assignee.display_name : "Sem responsável")
  );

  const details = document.createElement("details");
  details.className = "case-details";
  details.append(textNode("summary", "", "Detalhes"));
  const extra = document.createElement("dl");
  extra.className = "case-fields";
  extra.append(
    field("Situação do prazo", sla ? sla.explanation : "—"),
    field("Aberto em", formatDateTime(item.opened_at)),
    field("Atualizado em", formatDateTime(item.updated_at)),
    field("Canal", CHANNEL_LABELS[item.channel] || item.channel),
    field(
      "Motivos do encaminhamento",
      Array.isArray(item.reason_codes) && item.reason_codes.length
        ? item.reason_codes.join(", ")
        : "—"
    ),
    // Resumo ja mascarado na gravacao (telefone, e-mail, cartao, CNPJ, IP).
    field("Resumo (mascarado)", item.summary || "—")
  );
  details.append(extra);

  li.append(head, deadline, details);
  return li;
}

el("filter-domain").addEventListener("change", refreshQueue);
el("filter-color").addEventListener("change", refreshQueue);
el("refresh-button").addEventListener("click", refreshQueue);
el("filters").addEventListener("submit", (event) => event.preventDefault());

// Relatorio mensal: GET simples para /web/support/reports/monthly.csv (o
// cookie da sessao vai junto pelo path). Comeca no mes corrente.
(function initReportMonth() {
  const now = new Date();
  el("report-month").value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
})();

boot();
