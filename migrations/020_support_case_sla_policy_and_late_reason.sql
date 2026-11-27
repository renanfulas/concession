-- Migration 020 - relatorio mensal para a fiscalizacao (Fase 1, item 5).
--
-- sla_minutes / sla_basis: politica de prazo congelada na abertura do caso,
-- copiada do bloco `sla:` do domain.yaml (ou do SLA global) no INSERT. O
-- semaforo e o relatorio usam a politica gravada, entao mudar o domain.yaml
-- depois nao reescreve o prazo de casos ja abertos. As pausas
-- (waiting_customer) continuam descontadas a partir dos eventos. Casos
-- anteriores a esta migration ficam NULL e seguem com o SLA vigente.
--
-- late_reason: codigo obrigatorio ao fechar depois do prazo. Lista fechada,
-- sem texto livre, para nunca carregar dado pessoal para o relatorio.

ALTER TABLE support_cases
  ADD COLUMN sla_minutes INTEGER,
  ADD COLUMN sla_basis TEXT,
  ADD COLUMN late_reason TEXT;

ALTER TABLE support_cases
  ADD CONSTRAINT support_cases_sla_minutes_check
    CHECK (sla_minutes IS NULL OR sla_minutes > 0),
  ADD CONSTRAINT support_cases_late_reason_check
    CHECK (
      late_reason IS NULL
      OR late_reason IN (
        'aguardando_peca',
        'acesso_ao_local',
        'dependencia_externa',
        'volume_acima_da_capacidade',
        'classificacao_revista',
        'outro'
      )
    );
