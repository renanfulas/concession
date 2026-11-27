// Intake de solucoes de IA (/team/intake).
//
// Fala so com a API do intake (/web/support/intake/*), na mesma origem e com a
// mesma sessao HttpOnly da fila do time. Nada fica no armazenamento do
// navegador. Toda regra (criticidade, prazo, quem pode o que) vem da API; aqui
// so montamos o formulario e mostramos o resultado.
"use strict";

const API = {
  session: "/web/support/auth/session",
  options: "/web/support/intake/options",
  solutions: "/web/support/intake/solutions",
};

const LABELS = {
  solution_types: {
    interno: "Desenvolvimento interno",
    fornecedor: "Fornecedor",
    consultoria: "Consultoria",
    saas: "SaaS",
  },
  hosting_regions: {
    brasil: "Brasil",
    uniao_europeia: "União Europeia",
    estados_unidos: "Estados Unidos",
    outra: "Outra",
  },
  data_categories: {
    nenhum: "Nenhum dado pessoal",
    pessoal: "Dado pessoal",
    sensivel: "Dado sensível",
    biometrico_imagem: "Biometria ou imagem de pessoas",
    crianca: "Dado de criança ou adolescente",
  },
  data_subjects: {
    cidadao: "Cidadão",
    funcionario: "Funcionário",
    cliente_anunciante: "Cliente anunciante",
    fornecedor: "Fornecedor",
  },
  legal_bases: {
    nao_se_aplica: "Não se aplica (sem dado pessoal)",
    consentimento: "Consentimento",
    obrigacao_legal: "Obrigação legal",
    execucao_contrato: "Execução de contrato",
    legitimo_interesse: "Legítimo interesse",
    politica_publica: "Política pública",
    a_definir: "A definir",
  },
  rejection_reasons: {
    risco_sem_mitigacao: "Risco sem mitigação",
    base_legal_inadequada: "Base legal inadequada",
    duplica_solucao_existente: "Duplica solução existente",
    custo_desproporcional: "Custo desproporcional",
    fora_da_estrategia: "Fora da estratégia",
    outro: "Outro",
  },
};

const STATUS_LABELS = {
  submitted: "Submetido",
  in_review: "Em análise",
  needs_info: "Aguardando informação",
  approved: "Aprovado",
  approved_conditional: "Aprovado com condições",
  rejected: "Rejeitado",
  withdrawn: "Retirado",
};

const OUTCOME_LABELS = {
  em_analise_no_prazo: "No prazo",
  em_analise_atrasado: "Prazo estourado",
  decidido_no_prazo: "Decidido no prazo",
  decidido_fora_do_prazo: "Decidido fora do prazo",
  retirado: "Retirado",
};

const ERROR_LABELS = {
  self_review_forbidden: "Quem submeteu não pode analisar a própria solução.",
  not_the_reviewer: "Só quem assumiu a análise pode fazer isso.",
  not_the_submitter: "Só quem submeteu pode retirar o pedido.",
  invalid_transition: "Essa ação não vale no estado atual. Atualize a página.",
  missing_required_field: "Falta um campo obrigatório",
  invalid_field: "Campo inválido",
};

const FIELD_LABELS = {
  name: "nome",
  business_unit: "unidade de negócio",
  purpose: "finalidade",
  owner_name: "responsável",
  owner_role: "papel do responsável",
  data_categories: "dados tratados (marque ao menos um; 'nenhum' não combina com os outros)",
  data_subjects: "titulares",
  legal_basis: "base legal (dado pessoal sempre precisa de uma)",
  note: "nota",
  conditions: "condições",
  rejection_reason: "motivo da rejeição",
  ripd_reference: "referência do RIPD",
};

const TIME_ZONE = "America/Sao_Paulo";
const dateTimeFormat = new Intl.DateTimeFormat("pt-BR", {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const state = { options: null };

class ApiError extends Error {
  constructor(status, detail) {
    super(`api_error_${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" };
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
    throw new ApiError(response.status, payload && payload.detail);
  }
  return payload;
}

function $(id) {
  return document.getElementById(id);
}

function textNode(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  node.textContent = text;
  return node;
}

function formatDateTime(value) {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : dateTimeFormat.format(parsed);
}

function showView(name) {
  for (const view of ["loading", "login", "unavailable", "intake"]) {
    $(`view-${view}`).hidden = view !== name;
  }
}

function errorText(error) {
  if (error.status === 401) {
    return "Sessão expirada. Entre de novo pela fila do time.";
  }
  const detail = error.detail;
  if (detail && typeof detail === "object") {
    const base = ERROR_LABELS[detail.code] || "Não foi possível concluir.";
    return detail.field ? `${base}: ${FIELD_LABELS[detail.field] || detail.field}.` : base;
  }
  if (error.status === 403) {
    return "Pedido recusado pelo servidor.";
  }
  return "Não foi possível concluir agora. Tente de novo.";
}

// --------------------------------------------------------------------------- //
// Boot
// --------------------------------------------------------------------------- //

async function boot() {
  showView("loading");
  let session;
  try {
    session = await api(API.session);
  } catch (error) {
    showView(error.status === 401 ? "login" : "unavailable");
    return;
  }
  $("session-name").textContent = session.display_name || "";
  try {
    state.options = await api(API.options);
  } catch (error) {
    showView(error.status === 401 ? "login" : "unavailable");
    return;
  }
  buildForm(state.options);
  renderPolicy(state.options);
  $("not-durable").hidden = Boolean(state.options.durable);
  showView("intake");
  await refreshList();
}

function buildForm(options) {
  for (const select of document.querySelectorAll("select[data-options]")) {
    const key = select.dataset.options;
    for (const value of options[key] || []) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = (LABELS[key] && LABELS[key][value]) || value;
      select.append(option);
    }
  }
  buildChecks($("data-categories"), "data_categories", options.data_categories);
  buildChecks($("data-subjects"), "data_subjects", options.data_subjects);
}

function buildChecks(container, key, values) {
  for (const value of values) {
    const label = document.createElement("label");
    label.className = "check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = key;
    input.value = value;
    label.append(input, document.createTextNode(` ${LABELS[key][value] || value}`));
    container.append(label);
  }
}

function renderPolicy(options) {
  const days = options.sla_days;
  $("policy-basis").textContent =
    `${options.basis}. Prazo da análise: baixa ${days.baixa} dias, média ${days.media} dias, ` +
    `alta ${days.alta} dias (dias corridos). RIPD exigido para: ${options.ripd_required_for.join(", ") || "nenhum nível"}.`;
  const list = $("policy-rules");
  list.replaceChildren(
    ...options.rules.map((rule) => textNode("li", "", `${rule.level.toUpperCase()} · ${rule.reason}`))
  );
}

// --------------------------------------------------------------------------- //
// Submissao
// --------------------------------------------------------------------------- //

function formPayload(form) {
  const data = new FormData(form);
  const text = (name) => {
    const value = String(data.get(name) || "").trim();
    return value || null;
  };
  return {
    name: text("name") || "",
    business_unit: text("business_unit") || "",
    purpose: text("purpose") || "",
    owner_name: text("owner_name") || "",
    owner_role: text("owner_role") || "",
    solution_type: data.get("solution_type"),
    hosting_region: data.get("hosting_region"),
    legal_basis: data.get("legal_basis"),
    vendor: text("vendor"),
    model_provider: text("model_provider"),
    model_name: text("model_name"),
    data_categories: data.getAll("data_categories"),
    data_subjects: data.getAll("data_subjects"),
    automated_decision: data.has("automated_decision"),
    external_facing: data.has("external_facing"),
    human_in_loop: data.has("human_in_loop"),
  };
}

async function submitSolution(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = $("submit-message");
  try {
    const created = await api(API.solutions, { method: "POST", body: formPayload(form) });
    message.textContent =
      `${created.reference} registrado com criticidade ${created.criticality}. ` +
      `Prazo da análise: ${formatDateTime(created.sla.deadline_at)}.`;
    form.reset();
    $("submit-box").open = false;
    await refreshList();
  } catch (error) {
    message.textContent = errorText(error);
  }
  message.hidden = false;
}

// --------------------------------------------------------------------------- //
// Lista
// --------------------------------------------------------------------------- //

async function refreshList() {
  try {
    const result = await api(API.solutions);
    const list = $("solution-list");
    list.replaceChildren(...result.items.map(renderSolution));
    $("queue-empty").hidden = result.items.length > 0;
  } catch (error) {
    if (error.status === 401) {
      showView("login");
    }
  }
}

function lightOf(item) {
  if (item.decided_at) {
    return "none";
  }
  return item.sla.paused ? "paused" : item.sla.color;
}

function renderSolution(item) {
  const li = document.createElement("li");
  const light = lightOf(item);
  li.className = `case-card light-${light}`;

  const head = document.createElement("div");
  head.className = "case-head";
  head.append(
    textNode("span", `criticality criticality-${item.criticality}`, `Criticidade ${item.criticality}`),
    textNode("strong", "case-ref", item.reference),
    textNode("span", "status-chip", STATUS_LABELS[item.status] || item.status),
    textNode("span", "status-chip", OUTCOME_LABELS[item.outcome] || item.outcome)
  );

  const fields = document.createElement("dl");
  fields.className = "case-fields";
  const field = (label, value) => {
    const wrapper = document.createElement("div");
    wrapper.className = "field";
    wrapper.append(textNode("dt", "", label), textNode("dd", "", value));
    return wrapper;
  };
  fields.append(
    field("Solução", item.name),
    field("Unidade", item.business_unit),
    field("Responsável", `${item.owner_name} · ${item.owner_role}`),
    field(
      "Dados",
      item.data_categories.map((value) => LABELS.data_categories[value] || value).join(", ")
    ),
    field("Submetido por", item.submitted_by_me ? "você" : item.submitted_by_name),
    field("Análise", item.reviewer_name ? (item.reviewing_by_me ? "você" : item.reviewer_name) : "ninguém assumiu"),
    field(item.decided_at ? "Decidido em" : "Prazo da análise", formatDateTime(item.decided_at || item.sla.deadline_at))
  );

  const reasons = document.createElement("ul");
  reasons.className = "policy-rules";
  for (const reason of item.criticality_reasons) {
    reasons.append(textNode("li", "", reason.text));
  }

  const links = document.createElement("div");
  links.className = "action-row";
  const ficha = textNode("a", "button-ghost", "Ficha (.md)");
  ficha.href = `${API.solutions}/${encodeURIComponent(item.id)}/ficha.md`;
  links.append(ficha);

  li.append(head, textNode("p", "case-summary", item.purpose), fields, reasons, links);
  const actions = renderActions(item);
  if (actions) {
    li.append(actions);
  }
  return li;
}

// Which buttons to show mirrors the API rules; the API still decides.
function availableActions(item) {
  const mine = item.submitted_by_me;
  const reviewing = item.reviewing_by_me;
  switch (item.status) {
    case "submitted":
      return mine ? ["withdraw"] : ["claim"];
    case "in_review":
      return reviewing ? ["approve", "approve_with_conditions", "reject", "request_info", "release"] : [];
    case "needs_info":
      return [...(mine || reviewing ? ["resume"] : []), ...(mine ? ["withdraw"] : [])];
    default:
      return [];
  }
}

const ACTION_LABELS = {
  claim: "Assumir análise",
  release: "Devolver à fila",
  request_info: "Pedir informação",
  resume: "Retomar análise",
  approve: "Aprovar",
  approve_with_conditions: "Aprovar com condições",
  reject: "Rejeitar",
  withdraw: "Retirar pedido",
};

const NEEDS_FORM = new Set(["request_info", "approve", "approve_with_conditions", "reject", "withdraw"]);

function renderActions(item) {
  const actions = availableActions(item);
  if (actions.length === 0) {
    return null;
  }
  const wrapper = document.createElement("div");
  const row = document.createElement("div");
  row.className = "action-row";
  const slot = document.createElement("div");
  const message = textNode("p", "form-message", "");
  message.hidden = true;
  for (const action of actions) {
    const button = textNode("button", action === "claim" || action === "approve" ? "button-primary" : "button-ghost", ACTION_LABELS[action]);
    button.type = "button";
    button.addEventListener("click", () => {
      if (NEEDS_FORM.has(action)) {
        slot.replaceChildren(actionForm(item, action, message));
      } else {
        runAction(item, { action }, message);
      }
    });
    row.append(button);
  }
  wrapper.append(row, slot, message);
  return wrapper;
}

function actionForm(item, action, message) {
  const form = document.createElement("form");
  form.className = "action-form";
  const add = (label, control) => {
    const wrapper = document.createElement("label");
    wrapper.append(document.createTextNode(label), control);
    form.append(wrapper);
  };
  const note = document.createElement("textarea");
  note.name = "note";
  note.rows = 2;
  note.maxLength = 1000;
  add(action === "request_info" ? "O que falta" : "Nota", note);
  if (action === "approve_with_conditions") {
    const conditions = document.createElement("textarea");
    conditions.name = "conditions";
    conditions.rows = 2;
    conditions.maxLength = 1000;
    add("Condições", conditions);
  }
  if (action === "reject") {
    const reason = document.createElement("select");
    reason.name = "rejection_reason";
    for (const value of state.options.rejection_reasons) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = LABELS.rejection_reasons[value] || value;
      reason.append(option);
    }
    add("Motivo", reason);
  }
  if ((action === "approve" || action === "approve_with_conditions") && item.ripd_required) {
    const ripd = document.createElement("input");
    ripd.name = "ripd_reference";
    ripd.maxLength = 120;
    add("Referência do RIPD", ripd);
  }
  const submit = textNode("button", "button-primary", ACTION_LABELS[action]);
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const value = (name) => (data.has(name) ? String(data.get(name)).trim() || null : null);
    runAction(
      item,
      {
        action,
        note: value("note"),
        conditions: value("conditions"),
        rejection_reason: value("rejection_reason"),
        ripd_reference: value("ripd_reference"),
      },
      message
    );
  });
  return form;
}

async function runAction(item, payload, message) {
  try {
    await api(`${API.solutions}/${encodeURIComponent(item.id)}/transitions`, {
      method: "POST",
      body: payload,
    });
    await refreshList();
  } catch (error) {
    message.textContent = errorText(error);
    message.hidden = false;
  }
}

$("submit-form").addEventListener("submit", submitSolution);
boot();
