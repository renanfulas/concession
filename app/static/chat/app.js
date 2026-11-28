const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const quickPromptsList = document.querySelector("#quick-prompts-list");

const CHAT_ENDPOINT = "/web/chat";
const FEEDBACK_ENDPOINT = "/web/feedback";
const AUTH_SESSION_ENDPOINT = "/web/auth/session";
const AUTH_START_ENDPOINT = "/web/auth/whatsapp/start";
const AUTH_CONFIRM_ENDPOINT = "/web/auth/whatsapp/confirm";
const HANDOFF_CONSENT_ENDPOINT = "/web/handoff/consent";
const MAX_VISIBLE_SUPPORT_CODE = 80;

const QUICK_PROMPTS = [
  {
    id: "tela-apagada",
    title: "Tela ou relógio apagado",
    preview: "Registrar defeito com o código do ativo.",
    message: "O relógio REL-0423 na Teodoro Sampaio está com a tela apagada desde ontem.",
  },
  {
    id: "risco-seguranca",
    title: "Risco a pessoas",
    preview: "Fio exposto, vidro quebrado, estrutura solta.",
    message: "Tem um fio exposto soltando faísca no abrigo de ônibus ABR-1104.",
  },
  {
    id: "meus-dados",
    title: "Meus dados (LGPD)",
    preview: "Acesso, correção ou exclusão.",
    message: "Quero saber quais dados vocês têm sobre mim e pedir a exclusão.",
  },
  {
    id: "cameras",
    title: "Câmeras nos painéis",
    preview: "O que é medido e como.",
    message: "Os painéis digitais têm câmera? Vocês estão me filmando?",
  },
];

let loading = false;

renderQuickPrompts();
renderWelcomeMessage();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || loading) {
    return;
  }

  addMessage("user", message);
  document.querySelector(".chat")?.classList.add("is-started");
  input.value = "";
  resizeInput();
  setLoading(true);
  const loadingNode = addStatus("Lendo seu caso e montando a triagem...");

  try {
    const response = await sendChatMessage(message);
    loadingNode.remove();
    addAgentResponse(response);
  } catch (error) {
    loadingNode.remove();
    addAgentError(normalizeClientError(error));
  } finally {
    setLoading(false);
    input.focus();
  }
});

input.addEventListener("input", resizeInput);

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
}

function setLoading(next) {
  loading = next;
  input.disabled = next;
  sendButton.disabled = next;
}

async function sendChatMessage(message) {
  let response;

  try {
    response = await fetch(CHAT_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message }),
    });
  } catch {
    throw {
      kind: "network",
      message:
        "Não consegui conectar ao atendimento agora. Confira sua conexão e tente novamente.",
    };
  }

  const payload = await parseJsonSafely(response);
  const normalized = normalizeChatPayload(response, payload);

  if (!response.ok) {
    throw normalizeHttpError(response, normalized);
  }

  return normalized;
}

async function sendFeedback(payload) {
  const response = await fetch(FEEDBACK_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await parseJsonSafely(response);
  if (!response.ok) {
    const detail = getDetailMessage(data);
    throw new Error(detail || "Não consegui registrar seu feedback agora.");
  }

  return data;
}

async function parseJsonSafely(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    return null;
  }
}

function normalizeChatPayload(response, payload) {
  const requestId =
    asCleanString(payload?.request_id) ||
    asCleanString(payload?.support_code) ||
    asCleanString(response.headers.get("x-request-id"));
  const supportCode = asCleanString(payload?.support_code) || requestId;

  return {
    request_id: requestId,
    answer: asCleanString(payload?.answer),
    escalated: Boolean(payload?.escalated),
    handoff_reasons: Array.isArray(payload?.handoff_reasons)
      ? payload.handoff_reasons.filter(Boolean).map(String)
      : [],
    references: Array.isArray(payload?.references)
      ? payload.references.filter(Boolean).map(String)
      : [],
    support_code: supportCode,
    error_code: asCleanString(payload?.error_code),
    retry_after: response.headers.get("retry-after"),
    notices: Array.isArray(payload?.notices)
      ? payload.notices.filter(Boolean).map(String)
      : [],
    case: payload?.case && typeof payload.case === "object" ? payload.case : null,
    sources: Array.isArray(payload?.sources)
      ? payload.sources.filter((item) => item && item.title)
      : [],
    whatsapp_contact: payload?.whatsapp_contact === true,
    team_queue_url: safeLocalPath(payload?.team_queue_url),
  };
}

// Only same-origin absolute paths ("/team/"); anything else is dropped.
function safeLocalPath(value) {
  const path = typeof value === "string" ? value.trim() : "";
  return /^\/[a-z0-9/_-]*$/i.test(path) && !path.startsWith("//") ? path : null;
}

function normalizeHttpError(response, payload) {
  if (response.status === 429) {
    const waitSeconds = formatRetryAfter(payload.retry_after);
    return {
      kind: "http",
      request_id: payload.request_id,
      support_code: payload.support_code,
      error_code: payload.error_code || "rate_limited",
      message: waitSeconds
        ? `Recebi mensagens demais por agora. Espere ${waitSeconds} e tente novamente.`
        : "Recebi mensagens demais por agora. Espere um pouco e tente novamente.",
    };
  }

  if (response.status === 422) {
    return {
      kind: "http",
      request_id: payload.request_id,
      support_code: payload.support_code,
      error_code: payload.error_code || "invalid_request",
      message:
        "Não consegui enviar sua mensagem porque o pedido ficou inválido. Recarregue a página e tente novamente.",
    };
  }

  return {
    kind: "http",
    request_id: payload.request_id,
    support_code: payload.support_code,
    error_code: payload.error_code || `http_${response.status}`,
      message:
        "Não consegui fechar uma resposta segura agora. Tente novamente em instantes.",
  };
}

function normalizeClientError(error) {
  if (error && typeof error === "object" && "message" in error) {
    return {
      kind: error.kind || "client",
      message: String(error.message),
      request_id: asCleanString(error.request_id),
      support_code: asCleanString(error.support_code),
      error_code: asCleanString(error.error_code),
    };
  }

  return {
    kind: "client",
    message: "Não consegui responder agora. Tente novamente em instantes.",
  };
}

function addStatus(text) {
  const row = document.createElement("div");
  row.className = "message agent status";
  row.textContent = text;
  messages.appendChild(row);
  scrollToBottom();
  return row;
}

function addAgentResponse(response) {
  const row = document.createElement("div");
  row.className = "message agent";

  // Aviso fixo da regra (ex.: "ligue 193"): vem antes de tudo, como alerta.
  response.notices.forEach((notice) => row.appendChild(renderNotice(notice)));

  const text = stripNotices(response.answer, response.notices) || buildFallbackAnswer(response);
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  renderSafeMessageText(bubble, text);
  row.appendChild(bubble);

  if (response.case) {
    row.appendChild(renderCaseCard(response.case));
    if (response.team_queue_url) {
      row.appendChild(renderTeamQueueLink(response.team_queue_url));
    }
  } else if (response.escalated) {
    row.appendChild(renderEscalationNotice(response));
  }

  if (response.sources.length) {
    row.appendChild(renderSources(response.sources));
  }

  if (!response.case) {
    const metadata = renderSupportMeta(response, "default");
    if (metadata) {
      row.appendChild(metadata);
    }
  }

  if (response.request_id) {
    row.appendChild(renderFeedbackCard(response));
  }

  // O retorno por WhatsApp so e oferecido quando o servidor tem o canal ligado.
  if (response.escalated && response.request_id && response.case && response.whatsapp_contact) {
    row.appendChild(renderConsentPrompt(response.request_id, response.case));
  }

  messages.appendChild(row);
  scrollToBottom();
}

function stripNotices(answer, notices) {
  let text = String(answer || "");
  notices.forEach((notice) => {
    if (text.startsWith(notice)) {
      text = text.slice(notice.length).replace(/^\s+/, "");
    }
  });
  return text;
}

const SVG_NS = "http://www.w3.org/2000/svg";

function renderNotice(text) {
  const node = document.createElement("div");
  node.className = "notice";
  node.setAttribute("role", "note");

  const icon = document.createElementNS(SVG_NS, "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("fill", "none");
  icon.setAttribute("stroke-width", "2");
  icon.setAttribute("stroke-linecap", "round");
  icon.setAttribute("stroke-linejoin", "round");
  icon.setAttribute("aria-hidden", "true");
  icon.classList.add("notice-icon");
  ["M12 3 2 21h20L12 3Z", "M12 10v5", "M12 18h.01"].forEach((d) => {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    icon.appendChild(path);
  });

  const body = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = "Orientação importante";
  const message = document.createElement("span");
  message.textContent = text;
  body.append(title, message);

  node.append(icon, body);
  return node;
}

const PRIORITY_TAG = {
  urgent: "tag-urgent",
  high: "tag-high",
  normal: "tag-normal",
  low: "tag-low",
};

// Demo publica: leva o visitante para a fila do time, onde o caso acabou de entrar.
function renderTeamQueueLink(path) {
  const link = document.createElement("a");
  link.className = "team-queue-link";
  link.href = path;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "Ver este caso na fila do time ↗";
  return link;
}

function renderCaseCard(caseInfo) {
  const card = document.createElement("section");
  card.className = "case-card";
  card.setAttribute("aria-label", "Chamado registrado");

  const head = document.createElement("div");
  head.className = "case-card-head";
  const title = document.createElement("strong");
  title.textContent =
    caseInfo.status === "aguardando_confirmacao"
      ? "Chamado aberto · falta confirmar"
      : "Chamado registrado";
  const protocol = document.createElement("span");
  protocol.className = "case-protocol";
  protocol.textContent = `Protocolo ${caseInfo.protocol || ""}`;
  head.append(title, protocol);

  const details = document.createElement("dl");
  const priority = document.createElement("span");
  priority.className = `tag ${PRIORITY_TAG[caseInfo.priority] || "tag-normal"}`;
  priority.textContent = caseInfo.priority_label || caseInfo.priority || "";
  details.append(makeMetaItem("Prioridade", priority));
  if (caseInfo.deadline_label) {
    const deadline = document.createElement("span");
    deadline.className = "case-deadline";
    deadline.textContent = `Atendimento ${caseInfo.deadline_label}`;
    details.append(makeMetaItem("Prazo", deadline));
  }
  details.append(makeMetaItem("Base do prazo", caseInfo.basis || ""));
  details.append(makeMetaItem("Canal", caseInfo.channel_label || ""));

  const foot = document.createElement("p");
  foot.className = "case-card-foot";
  foot.textContent =
    caseInfo.status === "aguardando_confirmacao"
      ? "A equipe assume assim que você confirmar o contato abaixo."
      : "Uma pessoa da equipe assume a partir daqui. Guarde o protocolo para acompanhar.";

  card.append(head, details, foot);
  return card;
}

function renderSources(sources) {
  const wrapper = document.createElement("div");
  wrapper.className = "sources";

  const label = document.createElement("span");
  label.className = "sources-label";
  label.textContent = "Consultado:";
  wrapper.appendChild(label);

  sources.forEach((source) => {
    const item = document.createElement("span");
    item.className = "source";
    const kind = document.createElement("span");
    kind.className = "source-kind";
    kind.textContent = source.kind || "Documento";
    const title = document.createElement("span");
    title.textContent = source.title;
    item.append(kind, title);
    wrapper.appendChild(item);
  });

  return wrapper;
}

function addAgentError(error) {
  const requestId = error.support_code || error.request_id;
  const response = {
    request_id: error.request_id || requestId,
    support_code: requestId,
    error_code: error.error_code || "chat_unavailable",
    escalated: false,
    handoff_reasons: [],
    references: [],
  };

  addMessage(
    "agent",
    buildSupportMessage(error.message, requestId),
    response,
    "error",
  );
}

function addMessage(role, text, response = null, tone = "default") {
  const row = document.createElement("div");
  row.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = `bubble${tone === "error" ? " bubble-error" : ""}`;
  if (role === "agent") {
    renderSafeMessageText(bubble, text);
  } else {
    bubble.textContent = text;
  }
  row.appendChild(bubble);

  if (response?.escalated) {
    row.appendChild(renderEscalationNotice(response));
  }

  const metadata = renderSupportMeta(response, tone);
  if (metadata) {
    row.appendChild(metadata);
  }

  messages.appendChild(row);
  scrollToBottom();
  return row;
}

function renderEscalationNotice(response) {
  const handoff = document.createElement("div");
  handoff.className = "consent-card";

  const supportCode = shortProtocol(response.support_code || response.request_id);
  handoff.textContent = supportCode
    ? `Este caso precisa de uma pessoa. Guarde o protocolo ${supportCode} para continuar no suporte.`
    : "Este caso precisa de uma pessoa da equipe.";

  return handoff;
}

function renderSupportMeta(response, tone) {
  // So o protocolo curto: request_id e error_code sao internos e nunca vao
  // crus para a tela do cidadao.
  const code = shortProtocol(response?.support_code || response?.request_id);
  if (!code) {
    return null;
  }

  const wrapper = document.createElement("p");
  wrapper.className = `support-meta${tone === "error" ? " support-meta-error" : ""}`;
  wrapper.textContent = `Protocolo do atendimento: ${code}`;
  return wrapper;
}

function shortProtocol(value) {
  const text = asCleanString(value);
  const digits = text.replace(/[^0-9a-f]/gi, "").toUpperCase().slice(0, 8);
  if (digits.length < 8) {
    return clipSupportCode(text).toUpperCase().slice(0, 9);
  }
  return `${digits.slice(0, 4)}-${digits.slice(4)}`;
}

function makeMetaItem(label, value) {
  const fragment = document.createDocumentFragment();

  const term = document.createElement("dt");
  term.textContent = label;

  const detail = document.createElement("dd");
  if (value instanceof Node) {
    detail.appendChild(value);
  } else {
    detail.textContent = String(value);
  }

  fragment.append(term, detail);
  return fragment;
}

function renderFeedbackCard(response) {
  const wrapper = document.createElement("section");
  wrapper.className = "feedback-card";
  wrapper.setAttribute("aria-label", "Enviar feedback sobre a resposta");

  const title = document.createElement("p");
  title.className = "feedback-title";
  title.textContent = "Essa resposta ajudou?";

  const actions = document.createElement("div");
  actions.className = "feedback-actions";

  const positiveButton = buildFeedbackButton("Ajudou", true, response, wrapper);
  const negativeButton = buildFeedbackButton("Não ajudou", false, response, wrapper);

  actions.append(positiveButton, negativeButton);
  wrapper.append(title, actions);
  return wrapper;
}

function buildFeedbackButton(label, helpful, response, wrapper) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "feedback-button";
  button.textContent = label;

  button.addEventListener("click", async () => {
    if (wrapper.dataset.state === "sent") {
      return;
    }

    wrapper.dataset.state = "sending";
    setFeedbackButtonsDisabled(wrapper, true);

    try {
      await sendFeedback({
        request_id: response.request_id,
        helpful,
        reason: helpful ? "resolved" : "not_resolved",
      });
      wrapper.dataset.state = "sent";
      wrapper.replaceChildren(buildFeedbackResult(helpful));
    } catch (error) {
      wrapper.dataset.state = "idle";
      setFeedbackButtonsDisabled(wrapper, false);
      const message =
        error instanceof Error
          ? error.message
          : "Não consegui registrar seu feedback agora.";
      showFeedbackError(wrapper, message);
    }
  });

  return button;
}

function setFeedbackButtonsDisabled(wrapper, disabled) {
  wrapper.querySelectorAll(".feedback-button").forEach((button) => {
    button.disabled = disabled;
  });
}

function buildFeedbackResult(helpful) {
  const result = document.createElement("p");
  result.className = "feedback-result";
  result.textContent = helpful
    ? "Obrigado. Isso ajuda a manter a triagem mais útil."
    : "Obrigado. Vou marcar que esta resposta precisa de ajuste.";
  return result;
}

function showFeedbackError(wrapper, message) {
  const existing = wrapper.querySelector(".feedback-error");
  if (existing) {
    existing.textContent = message;
    return;
  }

  const error = document.createElement("p");
  error.className = "feedback-error";
  error.textContent = message;
  wrapper.appendChild(error);
}

// --- Consent gate (Sprint 4b): ask -> phone -> OTP -> name/email -> ticket. ---
// Auth is only requested here, at the moment a human handoff is actually on the
// table -- never up front. There is no server-side reminder job (the raw phone
// is never persisted); instead, the OTP step shows a local "still there?" nudge
// after the server-configured window, reusing the same resend endpoint.

function renderConsentPrompt(requestId, caseInfo) {
  const wrapper = document.createElement("section");
  wrapper.className = "consent-card";

  const title = document.createElement("p");
  title.className = "consent-title";
  title.textContent =
    caseInfo?.status === "aguardando_confirmacao"
      ? "Para a equipe assumir, confirme seu WhatsApp."
      : "Quer receber o retorno da equipe pelo WhatsApp?";

  const text = document.createElement("p");
  text.className = "consent-text";
  text.textContent =
    caseInfo?.status === "aguardando_confirmacao"
      ? "Enviamos um código para confirmar o número, por segurança."
      : "Enviamos um código para confirmar o número, por segurança. É opcional: o chamado já está registrado.";

  const actions = document.createElement("div");
  actions.className = "consent-actions";

  const yesButton = document.createElement("button");
  yesButton.type = "button";
  yesButton.className = "consent-button consent-button-primary";
  yesButton.textContent = "Sim, pelo WhatsApp";

  const noButton = document.createElement("button");
  noButton.type = "button";
  noButton.className = "consent-button";
  noButton.textContent = "Não precisa";

  yesButton.addEventListener("click", () => {
    wrapper.replaceChildren();
    beginConsentFlow(wrapper, requestId);
  });
  noButton.addEventListener("click", () => {
    wrapper.replaceChildren(buildConsentNotice("Sem problema. Se mudar de ideia, é só pedir de novo."));
  });

  actions.append(yesButton, noButton);
  wrapper.append(title, text, actions);
  return wrapper;
}

async function beginConsentFlow(container, requestId) {
  container.appendChild(buildConsentNotice("Verificando sua sessão..."));
  let sessionStatus = { status: "anonymous" };
  try {
    const response = await fetch(AUTH_SESSION_ENDPOINT);
    sessionStatus = (await parseJsonSafely(response)) || sessionStatus;
  } catch {
    // Falls back to anonymous below -- the phone step re-establishes the session.
  }
  container.replaceChildren();
  if (sessionStatus.status === "verified") {
    renderContactForm(container, requestId);
  } else {
    renderPhoneForm(container, requestId);
  }
}

function renderPhoneForm(container, requestId) {
  const form = document.createElement("form");
  form.className = "consent-form";

  const label = document.createElement("label");
  label.className = "consent-label";
  label.textContent = "Seu WhatsApp, com DDI (ex: +5511999999999)";

  const input = document.createElement("input");
  input.type = "tel";
  input.className = "consent-input";
  input.placeholder = "+5511999999999";
  input.autocomplete = "tel";
  input.required = true;

  const errorNode = buildConsentError();

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "consent-button consent-button-primary";
  submit.textContent = "Enviar código";

  form.append(label, input, errorNode, submit);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setConsentError(errorNode, "");
    submit.disabled = true;
    try {
      const response = await fetch(AUTH_START_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: input.value.trim() }),
      });
      const data = await parseJsonSafely(response);
      if (!response.ok) {
        throw buildConsentHttpError(response, data);
      }
      form.replaceWith(renderOtpForm(container, requestId, data));
    } catch (error) {
      setConsentError(errorNode, normalizeConsentError(error));
    } finally {
      submit.disabled = false;
    }
  });

  container.appendChild(form);
}

function renderOtpForm(container, requestId, startResponse) {
  const form = document.createElement("form");
  form.className = "consent-form";

  const label = document.createElement("label");
  label.className = "consent-label";
  label.textContent = "Código de 6 dígitos que chegou no seu WhatsApp";

  const input = document.createElement("input");
  input.type = "text";
  input.inputMode = "numeric";
  input.pattern = "\\d{6}";
  input.maxLength = 6;
  input.className = "consent-input";
  input.placeholder = "123456";
  input.autocomplete = "one-time-code";
  input.required = true;

  const errorNode = buildConsentError();
  const nudgeNode = document.createElement("p");
  nudgeNode.className = "consent-hint";
  nudgeNode.hidden = true;
  nudgeNode.textContent = "Ainda não recebeu? Você pode pedir um novo código.";

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "consent-button consent-button-primary";
  submit.textContent = "Confirmar código";

  const resend = document.createElement("button");
  resend.type = "button";
  resend.className = "consent-button";
  resend.textContent = "Reenviar código";
  resend.hidden = true;
  resend.addEventListener("click", () => {
    clearTimeout(nudgeTimer);
    form.remove();
    renderPhoneForm(container, requestId);
  });

  form.append(label, input, errorNode, nudgeNode, submit, resend);

  const nudgeTimer = setTimeout(() => {
    nudgeNode.hidden = false;
    resend.hidden = false;
  }, Math.max(1, Number(startResponse?.abandonment_reminder_seconds) || 900) * 1000);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setConsentError(errorNode, "");
    submit.disabled = true;
    try {
      const response = await fetch(AUTH_CONFIRM_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          challenge_id: startResponse.challenge_id,
          code: input.value.trim(),
        }),
      });
      const data = await parseJsonSafely(response);
      if (!response.ok) {
        throw buildConsentHttpError(response, data);
      }
      clearTimeout(nudgeTimer);
      form.replaceWith(renderContactForm(container, requestId));
    } catch (error) {
      setConsentError(errorNode, normalizeConsentError(error));
    } finally {
      submit.disabled = false;
    }
  });

  container.appendChild(form);
  return form;
}

function renderContactForm(container, requestId) {
  const form = document.createElement("form");
  form.className = "consent-form";

  const label = document.createElement("label");
  label.className = "consent-label";
  label.textContent = "Quase lá! Qual seu nome e e-mail para o atendente?";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.className = "consent-input";
  nameInput.placeholder = "Seu nome";
  nameInput.autocomplete = "name";
  nameInput.maxLength = 120;

  const emailInput = document.createElement("input");
  emailInput.type = "email";
  emailInput.className = "consent-input";
  emailInput.placeholder = "seu@email.com";
  emailInput.autocomplete = "email";
  emailInput.maxLength = 200;

  const errorNode = buildConsentError();

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "consent-button consent-button-primary";
  submit.textContent = "Abrir ticket";

  form.append(label, nameInput, emailInput, errorNode, submit);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setConsentError(errorNode, "");
    submit.disabled = true;
    try {
      const response = await fetch(HANDOFF_CONSENT_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          name: nameInput.value.trim() || null,
          email: emailInput.value.trim() || null,
        }),
      });
      const data = await parseJsonSafely(response);
      if (!response.ok) {
        throw buildConsentHttpError(response, data);
      }
      form.replaceWith(buildTicketConfirmation(data));
    } catch (error) {
      setConsentError(errorNode, normalizeConsentError(error));
    } finally {
      submit.disabled = false;
    }
  });

  container.appendChild(form);
  return form;
}

function buildTicketConfirmation(ticket) {
  const wrapper = document.createElement("div");
  wrapper.className = "consent-ticket";

  const title = document.createElement("p");
  title.className = "consent-ticket-title";
  title.textContent = `Retorno confirmado · chamado ${shortProtocol(ticket.support_case_id)}`;

  const meta = document.createElement("dl");
  meta.className = "support-meta";
  meta.append(makeMetaItem("Domínio", ticket.domain));
  if (ticket.opened_at) {
    meta.append(makeMetaItem("Aberto em", formatConsentTimestamp(ticket.opened_at)));
  }
  if (ticket.summary) {
    meta.append(makeMetaItem("Resumo", ticket.summary));
  }

  const note = document.createElement("p");
  note.className = "consent-hint";
  note.textContent = "A equipe vai responder pelo WhatsApp confirmado.";

  wrapper.append(title, meta, note);
  return wrapper;
}

function buildConsentNotice(text) {
  const node = document.createElement("p");
  node.className = "consent-hint";
  node.textContent = text;
  return node;
}

function buildConsentError() {
  const node = document.createElement("p");
  node.className = "consent-error";
  node.hidden = true;
  return node;
}

function setConsentError(node, message) {
  node.textContent = message;
  node.hidden = !message;
}

function buildConsentHttpError(response, payload) {
  const detail = (payload && payload.detail) || "";
  const messages = {
    invalid_phone: "Esse número não parece válido. Confira o formato (+DDI DDD número).",
    too_many_requests: "Muitas tentativas. Espere um pouco antes de tentar de novo.",
    otp_delivery_unavailable: "Não consegui enviar o código agora. Tente novamente em instantes.",
    invalid_or_expired_code: "Código inválido ou expirado. Peça um novo código.",
    otp_confirmation_required: "Sua sessão expirou. Vamos confirmar seu WhatsApp de novo.",
    support_case_not_found: "Não encontrei esse atendimento. Tente pedir para falar com um atendente de novo.",
    invalid_email: "Esse e-mail não parece válido.",
  };
  return new Error(messages[detail] || "Não consegui concluir agora. Tente novamente em instantes.");
}

function normalizeConsentError(error) {
  return error instanceof Error ? error.message : "Não consegui concluir agora. Tente novamente em instantes.";
}

function formatConsentTimestamp(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("pt-BR");
}

function renderSafeMessageText(container, text) {
  const lines = String(text || "").split(/\r?\n/);
  let list = null;
  let listType = null;

  lines.forEach((line, index) => {
    const bulletMatch = line.match(/^\s*[-*]\s+(.+)$/);
    const numberedMatch = line.match(/^\s*\d+[.)]\s+(.+)$/);

    if (bulletMatch || numberedMatch) {
      const nextListType = bulletMatch ? "ul" : "ol";
      if (!list || listType !== nextListType) {
        list = document.createElement(nextListType);
        list.className = "message-list";
        listType = nextListType;
        container.appendChild(list);
      }

      const item = document.createElement("li");
      item.textContent = bulletMatch ? bulletMatch[1] : numberedMatch[1];
      list.appendChild(item);
      return;
    }

    list = null;
    listType = null;

    if (line.trim()) {
      const paragraph = document.createElement("p");
      paragraph.textContent = line;
      container.appendChild(paragraph);
      return;
    }

    if (index > 0 && index < lines.length - 1) {
      container.appendChild(document.createElement("br"));
    }
  });
}

function renderQuickPrompts() {
  QUICK_PROMPTS.forEach((prompt) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quick-prompt";
    button.setAttribute("aria-label", `Usar pergunta: ${prompt.title}`);

    const title = document.createElement("span");
    title.className = "quick-prompt-title";
    title.textContent = prompt.title;

    const preview = document.createElement("span");
    preview.className = "quick-prompt-preview";
    preview.textContent = prompt.preview;

    button.append(title, preview);
    button.addEventListener("click", () => selectQuickPrompt(prompt.message));
    quickPromptsList.appendChild(button);
  });
}

function selectQuickPrompt(message) {
  input.value = message;
  resizeInput();
  input.focus();
}

function renderWelcomeMessage() {
  addMessage(
    "agent",
    "Para um defeito, diga o código do equipamento (etiqueta ou QR code) e o endereço ou um ponto de referência. Para seus dados, diga o que você quer: acesso, correção ou exclusão. Não peço CPF nem documento por aqui.",
  );
}

function buildFallbackAnswer(response) {
  const supportCode = response.support_code || response.request_id;
  if (supportCode) {
    return `Não recebi uma resposta completa agora. Tente novamente em instantes. Código de suporte: ${clipSupportCode(supportCode)}.`;
  }

  return "Não recebi uma resposta completa agora. Tente novamente em instantes.";
}

function buildSupportMessage(message, supportCode) {
  if (!supportCode) {
    return message;
  }

  return `${message} Código de suporte: ${clipSupportCode(supportCode)}.`;
}

function getDetailMessage(payload) {
  if (!payload) {
    return "";
  }

  if (typeof payload.detail === "string") {
    return payload.detail;
  }

  if (Array.isArray(payload.detail) && payload.detail.length) {
    return "Não consegui validar o feedback enviado.";
  }

  return "";
}

function clipSupportCode(value) {
  const text = asCleanString(value);
  if (!text) {
    return "";
  }

  return text.slice(0, MAX_VISIBLE_SUPPORT_CODE);
}

function formatRetryAfter(value) {
  const seconds = Number.parseInt(value || "", 10);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "";
  }

  if (seconds < 60) {
    return `${seconds}s`;
  }

  const minutes = Math.ceil(seconds / 60);
  return `${minutes} min`;
}

function asCleanString(value) {
  if (typeof value !== "string") {
    return "";
  }

  return value.trim();
}

function scrollToBottom() {
  messages.scrollTop = messages.scrollHeight;
}
