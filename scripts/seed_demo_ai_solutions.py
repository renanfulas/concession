"""Seed de demonstracao do intake de solucoes de IA (dados 100% ficticios).

Cria cinco solucoes ficticias que cobrem os tres niveis de criticidade e os
estados do fluxo (submetido, em analise, aguardando informacao, rejeitado),
mais duas pessoas ficticias da equipe::

    APP_ENV=development python -m scripts.seed_demo_ai_solutions
    APP_ENV=development python -m scripts.seed_demo_ai_solutions --reset

- ``Pessoa da BU (demo)`` submete todas as solucoes;
- ``Atendente Demo 1`` (o mesmo operador de ``scripts/seed_demo_cases.py`` e do
  login de desenvolvimento da /team) analisa algumas. Como quem submeteu nao
  pode analisar, o operador da demo consegue assumir e decidir as demais.

Mesmo caminho do app, sem regra duplicada: ``AiIntakeService`` sobre o
``PostgresSolutionRepository`` (criticidade, prazo gravado, separacao de
funcoes). O unico ajuste direto e a linha do tempo de cada solucao, recuada
junto com os eventos para o semaforo ter cores diferentes no momento do seed.

Guardas: as mesmas de ``seed_demo_cases`` (``APP_ENV`` explicito em
development/test e banco local). Marca: tudo que o seed cria foi submetido pela
pessoa ficticia da BU; ``--reset`` apaga so essas solucoes (os eventos vao
junto) e remove a pessoa ficticia. As referencias ``IA-AAAA-NNNN`` seguem a
sequencia do banco, entao mudam a cada novo seed.

Saida: referencia, criticidade, status e cor. Nenhum telefone ou segredo.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app.ai_intake.models import SolutionSubmission
from app.ai_intake.policy import load_policy
from app.ai_intake.repository import PostgresSolutionRepository
from app.ai_intake.service import AiIntakeService
from app.ai_intake.workflow import Actor, TransitionRequest
from app.db.runtime import DatabaseRuntime
from app.web_auth.service import _hmac_digest, normalize_phone
from scripts.seed_demo_cases import (
    SEED_STAFF_NAME,
    SeedError,
    SeedRefused,
    _runtime_settings,
    _upsert_staff,
    check_environment,
)

# Faixa ficticia: +55 11 90000-0002. Nunca um numero real.
SUBMITTER_PHONE = "+5511900000002"
SUBMITTER_NAME = "Pessoa da BU (demo)"


@dataclass(frozen=True)
class DemoSolution:
    key: str
    submission: SolutionSubmission
    # Transitions applied by the demo operator, in order.
    steps: tuple[TransitionRequest, ...]
    # How long ago it was submitted (the whole timeline moves back together).
    age: timedelta


def _submission(**values) -> SolutionSubmission:
    base = {
        "owner_name": "Gestor Demo",
        "owner_role": "Gerente (demo)",
        "automated_decision": False,
        "external_facing": False,
        "human_in_loop": True,
        "data_subjects": (),
    }
    base.update(values)
    return SolutionSubmission(**base)


DEMO_SOLUTIONS: tuple[DemoSolution, ...] = (
    DemoSolution(
        key="contagem-audiencia",
        submission=_submission(
            name="Contagem de audiencia por camera em painel digital",
            business_unit="Midia digital",
            purpose="Estimar quantas pessoas passam diante do painel, sem identificar ninguem.",
            owner_name="Gestora Demo",
            owner_role="Gerente de produto",
            solution_type="fornecedor",
            vendor="Fornecedor de visao computacional (demo)",
            model_provider="modelo embarcado no equipamento",
            hosting_region="uniao_europeia",
            data_categories=("biometrico_imagem",),
            data_subjects=("cidadao",),
            legal_basis="legitimo_interesse",
        ),
        steps=(),
        age=timedelta(days=2),
    ),
    DemoSolution(
        key="assistente-manutencao",
        submission=_submission(
            name="Assistente de manutencao do mobiliario urbano",
            business_unit="Operacoes",
            purpose="Atender o cidadao que relata defeito, classificar por regra e abrir chamado com prazo.",
            solution_type="interno",
            model_provider="OpenAI",
            model_name="gpt-4o-mini",
            hosting_region="brasil",
            data_categories=("pessoal",),
            data_subjects=("cidadao",),
            legal_basis="legitimo_interesse",
            external_facing=True,
        ),
        steps=(TransitionRequest("claim"),),
        age=timedelta(days=8),
    ),
    DemoSolution(
        key="resumo-contratos",
        submission=_submission(
            name="Resumo de contratos de concessao com LLM",
            business_unit="Juridico",
            purpose="Resumir clausulas de prazo e penalidade para a equipe de contratos.",
            solution_type="saas",
            vendor="Plataforma SaaS (demo)",
            model_provider="provedor de LLM (demo)",
            hosting_region="estados_unidos",
            data_categories=("pessoal",),
            data_subjects=("funcionario", "fornecedor"),
            legal_basis="execucao_contrato",
        ),
        steps=(
            TransitionRequest("claim"),
            TransitionRequest(
                "request_info",
                note="Confirmar clausulas de transferencia internacional no contrato do fornecedor.",
            ),
        ),
        age=timedelta(days=4),
    ),
    DemoSolution(
        key="previsao-falhas",
        submission=_submission(
            name="Previsao de falha de paineis",
            business_unit="Operacoes",
            purpose="Prever falha de painel digital a partir da telemetria do equipamento.",
            solution_type="interno",
            hosting_region="brasil",
            data_categories=("nenhum",),
            legal_basis="nao_se_aplica",
        ),
        steps=(),
        age=timedelta(days=6),
    ),
    DemoSolution(
        key="triagem-curriculos",
        submission=_submission(
            name="Triagem automatica de curriculos",
            business_unit="Pessoas",
            purpose="Ordenar candidatos e descartar os de menor aderencia sem revisao.",
            solution_type="saas",
            vendor="Plataforma de RH (demo)",
            hosting_region="brasil",
            data_categories=("pessoal",),
            data_subjects=("cidadao",),
            legal_basis="a_definir",
            automated_decision=True,
            human_in_loop=False,
        ),
        steps=(
            TransitionRequest("claim"),
            TransitionRequest(
                "reject",
                note="Decisao automatizada sobre candidatos sem revisao humana e sem base legal definida.",
                rejection_reason="risco_sem_mitigacao",
            ),
        ),
        age=timedelta(days=3),
    ),
)


def seed(database_url: str, identity_hash_secret: str) -> list[dict[str, str]]:
    runtime = DatabaseRuntime(_runtime_settings(database_url, None))
    try:
        reset(runtime, identity_hash_secret, remove_submitter=False)
        operator = Actor(_upsert_staff(database_url, identity_hash_secret), SEED_STAFF_NAME)
        submitter = Actor(_upsert_submitter(runtime, identity_hash_secret), SUBMITTER_NAME)
        service = AiIntakeService(load_policy(), PostgresSolutionRepository(runtime))
        for demo in DEMO_SOLUTIONS:
            solution_id = service.submit(demo.submission, submitter).record.id
            for step in demo.steps:
                service.transition(solution_id, step, operator)
            _move_back(runtime, solution_id, demo.age)
        return [
            {
                "reference": view.record.reference,
                "criticality": view.record.criticality,
                "status": view.record.status,
                "color": "pausado" if view.sla.paused else view.sla.color,
            }
            for view in service.queue()
            if view.record.submitted_by == submitter.staff_id
        ]
    finally:
        runtime.close()


def reset(
    runtime: DatabaseRuntime, identity_hash_secret: str, *, remove_submitter: bool = True
) -> int:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM staff_members WHERE phone_hash = %s",
                (_submitter_hash(identity_hash_secret),),
            )
            row = cursor.fetchone()
            if row is None:
                return 0
            cursor.execute("DELETE FROM ai_solutions WHERE submitted_by = %s", (row[0],))
            deleted = cursor.rowcount
            if remove_submitter:
                cursor.execute("DELETE FROM staff_sessions WHERE staff_id = %s", (row[0],))
                cursor.execute("DELETE FROM staff_login_hints WHERE staff_id = %s", (row[0],))
                cursor.execute(
                    """
                    DELETE FROM staff_members m WHERE m.id = %s
                      AND NOT EXISTS (SELECT 1 FROM ai_solution_events e WHERE e.actor_staff_id = m.id)
                      AND NOT EXISTS (SELECT 1 FROM support_case_events e WHERE e.actor_staff_id = m.id)
                    """,
                    (row[0],),
                )
            return deleted


def _upsert_submitter(runtime: DatabaseRuntime, identity_hash_secret: str) -> str:
    phone = normalize_phone(SUBMITTER_PHONE)
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO staff_members (phone_hash, phone_last4, display_name, status)
                VALUES (%s, %s, %s, 'active')
                ON CONFLICT (phone_hash) DO UPDATE
                SET display_name = EXCLUDED.display_name, status = 'active', updated_at = now()
                RETURNING id
                """,
                (_submitter_hash(identity_hash_secret), phone[-4:], SUBMITTER_NAME),
            )
            row = cursor.fetchone()
    if row is None:
        raise SeedError("nao foi possivel cadastrar a pessoa ficticia da BU")
    return str(row[0])


def _submitter_hash(identity_hash_secret: str) -> str:
    return _hmac_digest(identity_hash_secret, normalize_phone(SUBMITTER_PHONE))


def _move_back(runtime: DatabaseRuntime, solution_id: str, age: timedelta) -> None:
    seconds = age.total_seconds()
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ai_solutions
                SET submitted_at = submitted_at - make_interval(secs => %s),
                    updated_at = updated_at - make_interval(secs => %s),
                    decided_at = decided_at - make_interval(secs => %s)
                WHERE id = %s
                """,
                (seconds, seconds, seconds, solution_id),
            )
            cursor.execute(
                """
                UPDATE ai_solution_events
                SET created_at = created_at - make_interval(secs => %s)
                WHERE solution_id = %s
                """,
                (seconds, solution_id),
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="apaga so o que o seed criou")
    args = parser.parse_args(argv)
    database_url = os.getenv("DATABASE_URL")
    identity_secret = os.getenv("IDENTITY_HASH_SECRET", "")
    try:
        check_environment(os.getenv("APP_ENV"), database_url)
        if not identity_secret:
            raise SeedRefused("seed de demonstracao recusado: IDENTITY_HASH_SECRET ausente")
        if args.reset:
            runtime = DatabaseRuntime(_runtime_settings(database_url or "", None))
            try:
                print(f"solucoes do seed removidas: {reset(runtime, identity_secret)}")
            finally:
                runtime.close()
            return 0
        for row in seed(database_url or "", identity_secret):
            print(f"{row['reference']}  {row['criticality']:<5}  {row['status']:<20}  {row['color']}")
        return 0
    except SeedRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SeedError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
