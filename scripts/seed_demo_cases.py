"""Seed de demonstracao do console de suporte (dados 100% ficticios).

Cria casos de suporte ficticios nos dois dominios da demo
(``concessoes-manutencao`` e ``lgpd-titular``) cobrindo as prioridades que as
regras de cada ``domain.yaml`` produzem e as quatro leituras do semaforo
(vermelho, amarelo, verde e pausado), mais um operador ficticio ativo para o
console (``Atendente Demo 1``)::

    APP_ENV=development python -m scripts.seed_demo_cases
    APP_ENV=development python -m scripts.seed_demo_cases --reset

Usa ``DATABASE_URL`` e ``IDENTITY_HASH_SECRET`` do ambiente (o mesmo HMAC de
``scripts/manage_staff.py``, para o login OTP do console encontrar o
operador). ``PERSISTENCE_HASH_SECRET`` e opcional.

Mesmo caminho do app, sem regra duplicada:

- motivo: ``HandoffService.inspect_question`` sobre o texto ficticio;
- prioridade: ``resolve_case_priority`` com as ``escalation_rules`` do dominio;
- caso: ``OperationalRepository.record_chat`` (o mesmo INSERT de producao);
- dono e pausa: ``SupportCaseTransitionService`` (``claim``/``wait_customer``);
- cor: conferida no fim com ``compute_sla`` sobre ``list_active_cases``.

O unico ajuste direto e ``opened_at``, ancorado no relogio do banco
(``now() - intervalo``) para que a cor no momento do seed seja estavel.

Guardas: recusa rodar sem ``APP_ENV`` explicito em ``development`` ou ``test``
e com host de banco que nao seja local (``localhost``, ``127.0.0.1``, ``::1``
ou o servico ``postgres``/``postgres_test`` do compose/CI).

Marca: tudo que o seed cria usa ``channel='demo-seed'`` e ``request_id`` com
prefixo ``demo-seed-``. Rodar de novo substitui os casos do seed pelos mesmos
casos, com o relogio re-ancorado (idempotente: nunca duplica). ``--reset``
apaga somente as linhas marcadas e remove o operador ficticio (ou o desativa,
se ele ja tiver agido em caso fora do seed). Nada sai para outbox: os eventos
``handoff.requested`` gerados pelo ``record_chat`` sao removidos na hora.

Saida: apenas chave do caso, dominio, prioridade e cor; operador como
``display_name (****last4)``. Nenhum telefone completo, token ou segredo.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.db.operational import (
    PERSISTENCE_PERSISTED,
    ChatAuditInput,
    OperationalRepository,
)
from app.db.runtime import DatabaseRuntime
from app.domain_engine.loader import DomainLoader
from app.domain_engine.models import DomainConfig
from app.handoff.service import HandoffService
from app.handoff.taxonomy import resolve_case_priority, resolve_human_queue
from app.support.repository import SupportCaseRepository
from app.support.sla import _sla_minutes, compute_sla, domain_sla_overrides
from app.support.transitions import SupportCaseTransitionService
from app.web_auth.service import _hmac_digest, normalize_phone


SEED_CHANNEL = "demo-seed"
SEED_REQUEST_PREFIX = "demo-seed-"
SEED_DOMAINS = ("concessoes-manutencao", "lgpd-titular")
# Faixa ficticia: +55 11 90000-0001. Nunca um numero real.
SEED_STAFF_PHONE = "+5511900000001"
SEED_STAFF_NAME = "Atendente Demo 1"

ALLOWED_APP_ENVS = frozenset({"development", "test"})
LOCAL_DATABASE_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "postgres", "postgres_test"}
)

DEMO_ANSWER = (
    "Registrei o pedido e encaminhei para a equipe responsavel. "
    "Ambiente de demonstracao: prazos e dados ficticios."
)

# Margens largas em torno dos limites do semaforo (verde < 0.6, amarelo ate
# 1.0, vermelho acima) para a cor nao mudar durante a demo ou o teste.
RATIO_BY_COLOR = {"green": 0.25, "yellow": 0.8, "red": 1.5}


class SeedRefused(RuntimeError):
    """Ambiente ou banco fora do escopo permitido para o seed."""


class SeedError(RuntimeError):
    """O seed nao conseguiu produzir o estado esperado."""


@dataclass(frozen=True)
class DemoCase:
    key: str
    domain: str
    question: str
    expected_priority: str
    # Cor esperada no momento do seed: green, yellow, red ou paused.
    expected_color: str
    # Estado final: open, in_progress (claim) ou waiting_customer (claim + wait).
    state: str
    elapsed_ratio: float
    references: tuple[str, ...] = ()


_MANUT_REF = "knowledge/articles/inventario-ativos-demo.md"
_SLA_REF = "knowledge/articles/anexo-niveis-de-servico.md"

DEMO_CASES: tuple[DemoCase, ...] = (
    DemoCase(
        key="cm-01",
        domain="concessoes-manutencao",
        question=(
            "Fio exposto na base do relógio REL-0101 (Av. Paulista, altura do 900). "
            "Pedestres passando bem perto. [demo]"
        ),
        expected_priority="urgent",
        expected_color="red",
        state="open",
        elapsed_ratio=RATIO_BY_COLOR["red"],
        references=(_MANUT_REF, _SLA_REF),
    ),
    DemoCase(
        key="cm-02",
        domain="concessoes-manutencao",
        question=(
            "Vidro quebrado no abrigo ABR-1104, pedaços de vidro espalhados na "
            "calçada. [demo]"
        ),
        expected_priority="urgent",
        expected_color="green",
        state="in_progress",
        elapsed_ratio=RATIO_BY_COLOR["green"],
        references=(_MANUT_REF, _SLA_REF),
    ),
    DemoCase(
        key="cm-03",
        domain="concessoes-manutencao",
        question="Tela apagada no painel PNL-2010 desde o início da manhã. [demo]",
        expected_priority="high",
        expected_color="yellow",
        state="open",
        elapsed_ratio=RATIO_BY_COLOR["yellow"],
        references=(_MANUT_REF, _SLA_REF),
    ),
    DemoCase(
        key="cm-04",
        domain="concessoes-manutencao",
        question=(
            "Chegou notificação da fiscalização sobre o abrigo ABR-1290, "
            "na Av. Eusébio Matoso. [demo]"
        ),
        expected_priority="high",
        expected_color="red",
        state="in_progress",
        elapsed_ratio=RATIO_BY_COLOR["red"],
        references=(_MANUT_REF,),
    ),
    DemoCase(
        key="cm-05",
        domain="concessoes-manutencao",
        question="O relógio REL-0215 está com a hora errada, uns 20 minutos atrasado. [demo]",
        expected_priority="normal",
        expected_color="green",
        state="open",
        elapsed_ratio=RATIO_BY_COLOR["green"],
        references=(_MANUT_REF, _SLA_REF),
    ),
    DemoCase(
        key="cm-06",
        domain="concessoes-manutencao",
        question="Temperatura errada no relógio REL-0307, marcando 45 graus. [demo]",
        expected_priority="normal",
        expected_color="paused",
        state="waiting_customer",
        elapsed_ratio=0.5,
        references=(_MANUT_REF,),
    ),
    DemoCase(
        key="cm-07",
        domain="concessoes-manutencao",
        question="Abrigo ABR-1377 com pichação e cartaz colado na lateral. [demo]",
        expected_priority="low",
        expected_color="yellow",
        state="open",
        elapsed_ratio=RATIO_BY_COLOR["yellow"],
        references=(_MANUT_REF, _SLA_REF),
    ),
    DemoCase(
        key="cm-08",
        domain="concessoes-manutencao",
        question="Painel PNL-2101 da estação de bicicletas está sujo e com adesivo. [demo]",
        expected_priority="low",
        expected_color="green",
        state="open",
        elapsed_ratio=0.1,
        references=(_MANUT_REF,),
    ),
    DemoCase(
        key="lg-01",
        domain="lgpd-titular",
        question=(
            "Recebi um aviso estranho e acho que houve vazamento do meu cadastro "
            "no app de demonstração. [demo]"
        ),
        expected_priority="urgent",
        expected_color="red",
        state="open",
        elapsed_ratio=1.2,
    ),
    DemoCase(
        key="lg-02",
        domain="lgpd-titular",
        question=(
            "Quero as imagens da câmera do abrigo ABR-1104 de ontem à tarde. [demo]"
        ),
        expected_priority="high",
        expected_color="yellow",
        state="open",
        elapsed_ratio=RATIO_BY_COLOR["yellow"],
    ),
    DemoCase(
        key="lg-03",
        domain="lgpd-titular",
        question=(
            "Se ninguém responder vou abrir reclamação na ANPD sobre o uso do meu "
            "cadastro. [demo]"
        ),
        expected_priority="high",
        expected_color="paused",
        state="waiting_customer",
        elapsed_ratio=0.4,
    ),
    DemoCase(
        key="lg-04",
        domain="lgpd-titular",
        question="Quero uma cópia dos dados que vocês têm sobre mim. [demo]",
        expected_priority="normal",
        expected_color="green",
        state="in_progress",
        elapsed_ratio=RATIO_BY_COLOR["green"],
    ),
    DemoCase(
        key="lg-05",
        domain="lgpd-titular",
        question="Pedi para excluir meu cadastro e até agora nada aconteceu. [demo]",
        expected_priority="normal",
        expected_color="red",
        state="open",
        elapsed_ratio=1.1,
    ),
)


@dataclass(frozen=True)
class SeededCase:
    key: str
    case_id: str
    domain: str
    priority: str
    color: str


# --------------------------------------------------------------------------- #
# Guardas
# --------------------------------------------------------------------------- #


def check_environment(app_env: str | None, database_url: str | None) -> None:
    """Refuse anything that is not an explicit dev/test env on a local DB."""

    if app_env is None or app_env.strip().lower() not in ALLOWED_APP_ENVS:
        raise SeedRefused(
            "seed de demonstracao recusado: defina APP_ENV=development ou "
            "APP_ENV=test explicitamente"
        )
    if not database_url:
        raise SeedRefused("seed de demonstracao recusado: DATABASE_URL ausente")

    from psycopg.conninfo import conninfo_to_dict

    try:
        host = str(conninfo_to_dict(database_url).get("host") or "")
    except Exception as exc:  # noqa: BLE001 - nunca ecoar a URL (tem senha)
        raise SeedRefused("seed de demonstracao recusado: DATABASE_URL invalida") from exc
    hosts = [part.strip().lower() for part in host.split(",") if part.strip()]
    if not hosts or any(item not in LOCAL_DATABASE_HOSTS for item in hosts):
        raise SeedRefused(
            "seed de demonstracao recusado: o host do banco precisa ser local "
            "(localhost, 127.0.0.1, ::1, postgres ou postgres_test)"
        )


# --------------------------------------------------------------------------- #
# Seed
# --------------------------------------------------------------------------- #


def _runtime_settings(database_url: str, persistence_hash_secret: str | None) -> Any:
    # Mesmos campos que os testes de integracao usam; todas as frentes que
    # falam com o mundo externo (notificacao do time, ponte WhatsApp, arquivo
    # de conversa, gate de consentimento) ficam desligadas.
    return SimpleNamespace(
        persistence_backend="postgres",
        web_auth_storage_backend="disabled",
        enable_outbox_ingress=False,
        session_domain_store_backend="memory",
        database_url=database_url,
        database_pool_min_size=1,
        database_pool_max_size=2,
        database_connect_timeout_seconds=5,
        database_query_timeout_seconds=10,
        retrieval_backend="lexical",
        persistence_hash_secret=persistence_hash_secret or "",
        persistence_hash_version="hmac-sha256-v1",
        enable_conversation_archive=False,
        enable_handoff_consent_gate=False,
        enable_support_team_whatsapp_notify=False,
        enable_whatsapp_support_number=False,
        support_wa_enc_key=None,
    )


def load_seed_domains(domains_path: Path) -> dict[str, DomainConfig]:
    loader = DomainLoader(domains_path)
    configs: dict[str, DomainConfig] = {}
    for name in SEED_DOMAINS:
        config = loader.load(name)
        if config is None:
            raise SeedError(f"dominio {name} nao carregou de {domains_path}")
        configs[name] = config
    return configs


def resolve_demo_case(config: DomainConfig, case: DemoCase) -> tuple[list[str], str]:
    """Reasons and priority exactly as the chat routes resolve them."""

    reasons = HandoffService().inspect_question(config, case.question)
    priority = resolve_case_priority(config, reasons)
    return reasons, priority


def seed_demo_cases(
    database_url: str,
    *,
    app_env: str | None,
    identity_hash_secret: str,
    persistence_hash_secret: str | None = None,
    domains_path: Path = Path("domains"),
) -> list[SeededCase]:
    check_environment(app_env, database_url)
    if not identity_hash_secret:
        raise SeedRefused("IDENTITY_HASH_SECRET e obrigatorio para cadastrar o operador")

    configs = load_seed_domains(domains_path)
    resolved: dict[str, tuple[list[str], str]] = {}
    for case in DEMO_CASES:
        reasons, priority = resolve_demo_case(configs[case.domain], case)
        if priority != case.expected_priority:
            raise SeedError(
                f"caso {case.key}: regras do dominio resolveram prioridade "
                f"{priority}, esperado {case.expected_priority} (domain.yaml mudou?)"
            )
        resolved[case.key] = (reasons, priority)

    staff_id = _upsert_staff(database_url, identity_hash_secret)

    runtime = DatabaseRuntime(_runtime_settings(database_url, persistence_hash_secret))
    runtime.open()
    try:
        _upsert_domains(runtime, configs)
        _delete_seed_rows(runtime)

        operational = OperationalRepository(runtime)
        transitions = SupportCaseTransitionService(runtime)
        overrides = domain_sla_overrides(configs.values())
        case_ids: dict[str, str] = {}
        for case in DEMO_CASES:
            reasons, priority = resolved[case.key]
            request_id = f"{SEED_REQUEST_PREFIX}{case.key}"
            result = operational.record_chat(
                ChatAuditInput(
                    request_id=request_id,
                    domain=case.domain,
                    session_id=None,
                    question=case.question,
                    answer=DEMO_ANSWER,
                    confidence=0.9,
                    escalated=True,
                    handoff_reasons=reasons,
                    references=list(case.references),
                    error_code=None,
                    channel=SEED_CHANNEL,
                    requires_human_queue=resolve_human_queue(
                        configs[case.domain], reasons
                    ),
                    case_priority=priority,
                )
            )
            if result.persistence_status != PERSISTENCE_PERSISTED:
                raise SeedError(f"caso {case.key}: persistencia indisponivel")
            case_id = _find_seed_case(runtime, request_id)
            sla_minutes = _sla_minutes(
                priority, SimpleNamespace(), overrides.get(case.domain)
            )
            _anchor_opened_at(
                runtime, case_id, elapsed_seconds=case.elapsed_ratio * sla_minutes * 60
            )
            if case.state in {"in_progress", "waiting_customer"}:
                transitions.apply(
                    case_id=case_id, action="claim", actor_staff_id=staff_id, note=None
                )
            if case.state == "waiting_customer":
                transitions.apply(
                    case_id=case_id,
                    action="wait_customer",
                    actor_staff_id=staff_id,
                    note="aguardando retorno do solicitante (demo)",
                )
            case_ids[case.key] = case_id

        # O seed nao dispara nada para fora: remove os handoff.requested que o
        # record_chat enfileirou para os casos marcados.
        _delete_seed_outbox(runtime)
        return _verify_colors(runtime, case_ids, overrides)
    finally:
        runtime.close()


def reset_demo_cases(
    database_url: str,
    *,
    app_env: str | None,
    identity_hash_secret: str | None,
) -> dict[str, int | str]:
    check_environment(app_env, database_url)
    runtime = DatabaseRuntime(_runtime_settings(database_url, None))
    runtime.open()
    try:
        counts: dict[str, int | str] = dict(_delete_seed_rows(runtime))
    finally:
        runtime.close()
    counts["staff"] = (
        _remove_staff(database_url, identity_hash_secret)
        if identity_hash_secret
        else "kept (IDENTITY_HASH_SECRET ausente)"
    )
    return counts


def _upsert_staff(database_url: str, identity_hash_secret: str) -> str:
    import psycopg

    from scripts.manage_staff import _add

    with psycopg.connect(database_url) as connection:
        if _add(connection, identity_hash_secret, SEED_STAFF_PHONE, SEED_STAFF_NAME) != 0:
            raise SeedError("nao foi possivel cadastrar o operador ficticio")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM staff_members WHERE phone_hash = %s",
                (_staff_phone_hash(identity_hash_secret),),
            )
            row = cursor.fetchone()
    if row is None:
        raise SeedError("operador ficticio nao encontrado apos o cadastro")
    return str(row[0])


def _remove_staff(database_url: str, identity_hash_secret: str) -> str:
    import psycopg

    phone_hash = _staff_phone_hash(identity_hash_secret)
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM staff_members WHERE phone_hash = %s", (phone_hash,))
            row = cursor.fetchone()
            if row is None:
                return "absent"
            staff_id = row[0]
            cursor.execute(
                """
                SELECT
                  EXISTS (SELECT 1 FROM support_cases WHERE assignee_staff_id = %s)
                  OR EXISTS (SELECT 1 FROM support_case_events WHERE actor_staff_id = %s)
                  -- Migration 021: the intake also references staff members.
                  OR EXISTS (
                    SELECT 1 FROM ai_solutions
                    WHERE submitted_by = %s OR reviewer_staff_id = %s
                  )
                  OR EXISTS (SELECT 1 FROM ai_solution_events WHERE actor_staff_id = %s)
                """,
                (staff_id, staff_id, staff_id, staff_id, staff_id),
            )
            still_referenced = bool(cursor.fetchone()[0])
            if still_referenced:
                # Agiu em caso fora do seed: desativa em vez de apagar trilha.
                cursor.execute(
                    "UPDATE staff_members SET status = 'disabled', updated_at = now() "
                    "WHERE id = %s",
                    (staff_id,),
                )
                cursor.execute("DELETE FROM staff_sessions WHERE staff_id = %s", (staff_id,))
                cursor.execute("DELETE FROM staff_login_hints WHERE staff_id = %s", (staff_id,))
                outcome = "disabled"
            else:
                cursor.execute("DELETE FROM staff_members WHERE id = %s", (staff_id,))
                outcome = "deleted"
        connection.commit()
    return outcome


def _staff_phone_hash(identity_hash_secret: str) -> str:
    return _hmac_digest(identity_hash_secret, normalize_phone(SEED_STAFF_PHONE))


def _upsert_domains(runtime: DatabaseRuntime, configs: dict[str, DomainConfig]) -> None:
    # record_chat exige a linha em `domains` (normalmente criada pela ingestao).
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            for config in configs.values():
                cursor.execute(
                    """
                    INSERT INTO domains (name, display_name)
                    VALUES (%s, %s)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    (config.name, config.display_name),
                )


def _delete_seed_rows(runtime: DatabaseRuntime) -> dict[str, int]:
    """Delete only rows carrying the seed mark (channel + request_id prefix)."""

    like = f"{SEED_REQUEST_PREFIX}%"
    counts: dict[str, int] = {}
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM support_case_events
                WHERE case_id IN (
                  SELECT id FROM support_cases
                  WHERE channel = %s AND request_id LIKE %s
                )
                """,
                (SEED_CHANNEL, like),
            )
            counts["events"] = cursor.rowcount
            cursor.execute(
                "DELETE FROM support_cases WHERE channel = %s AND request_id LIKE %s",
                (SEED_CHANNEL, like),
            )
            counts["cases"] = cursor.rowcount
            cursor.execute(
                "DELETE FROM operational_outbox WHERE request_id LIKE %s",
                (like,),
            )
            counts["outbox"] = cursor.rowcount
            cursor.execute(
                "DELETE FROM chat_audits WHERE channel = %s AND request_id LIKE %s",
                (SEED_CHANNEL, like),
            )
            counts["audits"] = cursor.rowcount
    return counts


def _delete_seed_outbox(runtime: DatabaseRuntime) -> None:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM operational_outbox WHERE request_id LIKE %s",
                (f"{SEED_REQUEST_PREFIX}%",),
            )


def _find_seed_case(runtime: DatabaseRuntime, request_id: str) -> str:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM support_cases WHERE channel = %s AND request_id = %s",
                (SEED_CHANNEL, request_id),
            )
            row = cursor.fetchone()
    if row is None:
        raise SeedError(f"caso {request_id} nao foi aberto pelo record_chat")
    return str(row[0])


def _anchor_opened_at(runtime: DatabaseRuntime, case_id: str, *, elapsed_seconds: float) -> None:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE support_cases
                SET opened_at = now() - make_interval(secs => %s),
                    updated_at = now()
                WHERE id = %s AND channel = %s
                """,
                (float(elapsed_seconds), case_id, SEED_CHANNEL),
            )


def _verify_colors(
    runtime: DatabaseRuntime,
    case_ids: dict[str, str],
    overrides: dict,
) -> list[SeededCase]:
    repository = SupportCaseRepository(runtime)
    by_id = {}
    db_now = None
    for domain in SEED_DOMAINS:
        active = repository.list_active_cases(domain=domain, status=None, cap=500)
        db_now = active.db_now or db_now
        for summary in active.cases:
            by_id[summary.case_id] = (summary, active.db_now)

    seeded: list[SeededCase] = []
    for case in DEMO_CASES:
        entry = by_id.get(case_ids[case.key])
        if entry is None:
            raise SeedError(f"caso {case.key} nao aparece na fila ativa")
        summary, case_db_now = entry
        sla = compute_sla(
            summary.priority,
            summary.opened_at,
            summary.status,
            case_db_now,
            SimpleNamespace(),
            waiting_seconds=summary.waiting_seconds,
            domain_sla=overrides.get(summary.domain),
        )
        color = "paused" if sla.paused else sla.color
        if color != case.expected_color:
            raise SeedError(
                f"caso {case.key}: cor {color}, esperado {case.expected_color}"
            )
        seeded.append(
            SeededCase(
                key=case.key,
                case_id=summary.case_id,
                domain=summary.domain,
                priority=summary.priority,
                color=color,
            )
        )
    return seeded


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed ficticio do console de suporte (somente dev/test, banco local)."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="apaga somente as linhas criadas pelo seed e remove o operador ficticio",
    )
    args = parser.parse_args(argv)

    app_env = os.environ.get("APP_ENV")
    database_url = os.environ.get("DATABASE_URL")
    identity_hash_secret = os.environ.get("IDENTITY_HASH_SECRET")
    try:
        if args.reset:
            counts = reset_demo_cases(
                database_url or "",
                app_env=app_env,
                identity_hash_secret=identity_hash_secret,
            )
            print("reset do seed de demonstracao:")
            for name, value in counts.items():
                print(f"  {name}: {value}")
            return 0
        seeded = seed_demo_cases(
            database_url or "",
            app_env=app_env,
            identity_hash_secret=identity_hash_secret or "",
            persistence_hash_secret=os.environ.get("PERSISTENCE_HASH_SECRET"),
            domains_path=Path(os.environ.get("DOMAINS_PATH", "domains")),
        )
    except SeedRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SeedError as exc:
        print(f"seed falhou: {exc}", file=sys.stderr)
        return 1

    print(f"{len(seeded)} casos ficticios (channel={SEED_CHANNEL}):")
    for item in seeded:
        print(f"  {item.key}\t{item.domain}\t{item.priority}\t{item.color}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
