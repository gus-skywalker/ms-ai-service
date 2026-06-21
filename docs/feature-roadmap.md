# AI Service Feature Roadmap

## Estado atual dos modelos

| funcionalidade | modelo ativo | versão | armazenamento | observações |
| -------------- | ------------ | ------- | ------------- | ----------- |
| `prediction` | média mensal de despesas | `v1` | `models/prediction/v1/{userId}` | Baseline simples; salva `avg_expense` num JSON via `save_model`. Ainda falta métricas de qualidade. |
| `autocat` | TF-IDF `vectorizer` | `v1` | `models/autocat/v1/{userId}` | Forma vocabular com `sklearn.TfidfVectorizer`. não há fallback multimodel. |
| `anomaly` | stats (median + MAD) | `v1` | `storage/user_data/{userId}/anomaly_stats.json` | Exporta apenas estatísticas; o endpoint lê o JSON para classificar meses. |
| `cashflow` | forecasts + alerts | n/a | `storage/user_data/{userId}/monthly_series.parquet` | Usa heurísticas e simulações, sem persistir modelo. |
| `savings` | recomendação de plano | n/a | derivado dos arquivos mensais | Ainda baseado em lógica de regra; sem persistência explícita. |

Drivers de persistência: `app/core/models_registry.py` usa joblib/pickle para each model, as atividades de trainer gravam o JSON em `storage/user_data` e `models/<feature>/v1`.

## Próximos passos idealizados por funcionalidade

### 1. Prediction
- **Necessidades imediatas:** métricas de validação (MAPE ou MAE) e monitoramento de drift nos `monthly_series.parquet`. Semana 1.
- **Melhorias:** adicionar `models/prediction/v1/{userId}/meta.json` com últimos dados usados, versão dos dados e `avg_expense` vs `actual`. Semana 2.
- **Infraestruturas:** pipeline para validar novas previsões contra transações reais (batch ou streaming). Quinzena 2.

### 2. Autocat
- **Necessidade:** fallback para vocabulários limitados; a função atual só salva o vectorizer. Planejar `textEmbedding` ou boosting.
- **Melhoria curta:** adicionar `model_metadata.json` com tamanho do vocabulário e data de treino; se o vocabulário for menor que 5, registrar alerta (evita sempre 1 categoria). Semana 1.
- **Contrato de segurança:** substituir fallback para categoria fixa (`miscellaneous`/`Outros`, id `14`) por abstention/unknown. O `budget-api` já filtra esse fallback como não aplicável, mas o `ai-service` também deve parar de emitir categoria genérica quando o modelo falha, recebe descrição vazia ou tem histórico insuficiente.
- **Longo prazo:** treinar modelo supervisionado com anotações e salvar `model.joblib`. Necessita de dataset rotulado. 1 mês.

### 3. Anomaly
- **Curto:** adicionar thresholds configuráveis e persistir `anomaly_stats.json` com percentis extras; exportar `training_status.json` com última data de treino. Já salvamos stats, basta enriquecer.
- **Médio:** gerenciar `feature` names, integrar `cashflow` deficits para insights combinados. 2-3 semanas.

### 4. Cashflow
- **Falta:** sistemas de alerts persistentes guardando `CashflowAlert` históricos; now done per request only. Adicionar `storage/user_data/{userId}/cashflow_alerts.json`.
- **Melhorias:** a previsão atualmente usa heurística; trocar por regressão simples treinada no `monthly_series`. 3 semanas.

### 5. Savings
- **Necessidade:** persistir plano gerado (`SavingsPlan`) e actions para auditoria. Atualmente calculamos em runtime.
- **Recomendações:** deixar `training_status.json` mostrar `savings_plan` e `progress`. Também criar `SavingsAction` persistente para que Java possa sugerir ações repetidas. 2 semanas.

## Observabilidade e documentação
- Adicionar `docs/deployment.md` com passos do Railway (já temos README). Padrão: `training_status.json` + `/internal/ai/health` para monitoria.
- Documentar a arquitetura no `docs/feature-roadmap.md` e referenciar na sprint backlog.

## Prioridades recomendadas
1. **Documentar e monitorar** — finalize este roadmap, garantir `training_status.json` enriquecido, e criar alertas no Railway via `/internal/ai/health` e `/metrics`. Já coberto parcialmente.
2. **Persistir metadados** — `models/.../meta.json` para prediction/autocat; `training_status.json` inclui campo `modelVersion`, `modelPath`, `metrics`. Desdobramento: atualize `app/core/trainers.py` para escrever meta (exemplo: append to persisted JSON). 2–3 dias.
3. **Productize cashflow/savings** — persistir cálculos + treinar regressões/lógicas mais robustas; planejar para sprint 2.
4. **Integrar retraining monitor** — `app/core/training_queue.py` já registra job status; adicionar cron job/endpoint para re-enfileirar usuários com dados novos (futuro). 2 semanas.

## Documentação adicional a entregar
- Cada funcionalidade precisa de um bloco no backlog/lista de tarefas: `docs/feature-roadmap.md` (este arquivo). Reutilize-o para planejar melhorias e atualize conforme você fizer deploys.
- Mantenha o `README.md` atualizado com endpoints e o `railway.json` para deploy.
