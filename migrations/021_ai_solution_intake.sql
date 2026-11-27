-- Migration 021 - intake e inventario de solucoes de IA.
--
-- Uma unidade de negocio submete uma iniciativa de IA; a criticidade sai de
-- regras deterministicas (governance/ai-intake.yaml) e o prazo da analise fica
-- gravado na submissao (mesmo padrao da migration 020): mudar a politica
-- depois nao reescreve pedidos ja abertos.
--
-- Dados pessoais: so o nome e o papel do responsavel (dado de funcionario,
-- necessario ao inventario). Nada de e-mail, telefone ou documento. Textos
-- livres chegam aqui ja mascarados por sanitize_for_persistence.

CREATE SEQUENCE ai_solution_reference_seq;

CREATE TABLE ai_solutions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reference TEXT NOT NULL,
  name TEXT NOT NULL,
  business_unit TEXT NOT NULL,
  purpose TEXT NOT NULL,
  owner_name TEXT NOT NULL,
  owner_role TEXT NOT NULL,
  solution_type TEXT NOT NULL,
  vendor TEXT,
  model_provider TEXT,
  model_name TEXT,
  hosting_region TEXT NOT NULL,
  data_categories TEXT[] NOT NULL,
  data_subjects TEXT[] NOT NULL DEFAULT '{}',
  legal_basis TEXT NOT NULL,
  automated_decision BOOLEAN NOT NULL,
  external_facing BOOLEAN NOT NULL,
  human_in_loop BOOLEAN NOT NULL,
  criticality TEXT NOT NULL,
  criticality_reasons TEXT[] NOT NULL DEFAULT '{}',
  ripd_required BOOLEAN NOT NULL,
  status TEXT NOT NULL DEFAULT 'submitted',
  sla_minutes INTEGER NOT NULL,
  sla_basis TEXT NOT NULL,
  submitted_by UUID NOT NULL REFERENCES staff_members(id),
  reviewer_staff_id UUID REFERENCES staff_members(id),
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ,
  decision_note TEXT,
  conditions TEXT,
  rejection_reason TEXT,
  ripd_reference TEXT,
  CONSTRAINT ai_solutions_reference_unique UNIQUE (reference),
  CONSTRAINT ai_solutions_solution_type_check
    CHECK (solution_type IN ('interno', 'fornecedor', 'consultoria', 'saas')),
  CONSTRAINT ai_solutions_hosting_region_check
    CHECK (hosting_region IN ('brasil', 'uniao_europeia', 'estados_unidos', 'outra')),
  CONSTRAINT ai_solutions_data_categories_check
    CHECK (
      cardinality(data_categories) > 0
      AND data_categories <@ ARRAY[
        'nenhum', 'pessoal', 'sensivel', 'biometrico_imagem', 'crianca'
      ]::TEXT[]
    ),
  CONSTRAINT ai_solutions_data_subjects_check
    CHECK (
      data_subjects <@ ARRAY[
        'cidadao', 'funcionario', 'cliente_anunciante', 'fornecedor'
      ]::TEXT[]
    ),
  CONSTRAINT ai_solutions_legal_basis_check
    CHECK (
      legal_basis IN (
        'nao_se_aplica', 'consentimento', 'obrigacao_legal', 'execucao_contrato',
        'legitimo_interesse', 'politica_publica', 'a_definir'
      )
    ),
  CONSTRAINT ai_solutions_criticality_check
    CHECK (criticality IN ('baixa', 'media', 'alta')),
  CONSTRAINT ai_solutions_status_check
    CHECK (
      status IN (
        'submitted', 'in_review', 'needs_info', 'approved',
        'approved_conditional', 'rejected', 'withdrawn'
      )
    ),
  CONSTRAINT ai_solutions_sla_minutes_check CHECK (sla_minutes > 0),
  CONSTRAINT ai_solutions_rejection_reason_check
    CHECK (
      rejection_reason IS NULL
      OR rejection_reason IN (
        'risco_sem_mitigacao', 'base_legal_inadequada', 'duplica_solucao_existente',
        'custo_desproporcional', 'fora_da_estrategia', 'outro'
      )
    ),
  CONSTRAINT ai_solutions_decided_at_check
    CHECK (
      (status IN ('approved', 'approved_conditional', 'rejected', 'withdrawn'))
      = (decided_at IS NOT NULL)
    )
);

CREATE INDEX ai_solutions_status_idx ON ai_solutions (status, submitted_at);

CREATE TABLE ai_solution_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  solution_id UUID NOT NULL REFERENCES ai_solutions(id) ON DELETE CASCADE,
  actor_staff_id UUID NOT NULL REFERENCES staff_members(id),
  action TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  note_sanitized TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ai_solution_events_solution_idx
  ON ai_solution_events (solution_id, created_at);
