.# Melhorias Planejadas para o Microserviço de IA (Python)

Este documento resume as melhorias e funcionalidades futuras para o microserviço `ai-service` em Python, mantendo compatibilidade com o backend Java (`budget-api`) e o frontend Vue.

## 1. Objetivos Gerais

- Sair de regras heurísticas simples para modelos estatísticos/ML mais realistas.
- Manter **os contratos de API atuais** (mesmos endpoints e payloads) para não quebrar o Java nem o frontend.
- Usar sempre o `userId` extraído do **token JWT** (não vindo no body) para personalizar previsões e análises.
- Criar uma arquitetura organizada por "features" (prediction, anomaly, auto-categorization, savings, cashflow).
- Permitir evolução futura (mais algoritmos, re-treinamento, armazenamento de modelos) sem reescrever o serviço.

Endpoints já expostos pelo Python (mantidos):

- `POST /api/v1/ai/monthly-expenses-prediction`
- `POST /api/v1/ai/anomaly-detection`
- `POST /api/v1/ai/auto-categorize`
- `POST /api/v1/ai/savings-recommendations`
- `POST /api/v1/ai/cashflow-insights`

---

## 2. Arquitetura Proposta (Organização de Código)

Criar a seguinte estrutura de pastas em `app/` (sem mudar os endpoints em `main.py`):

```text
app/
  main.py                      # mantém as rotas FastAPI (contrato estável)
  core/
    config.py                  # carregamento de env vars e configs gerais
    models_registry.py         # registro/carregamento/salvamento de modelos (por feature/user)
  utils/
    preprocessing.py           # limpeza de dados, agregações, features comuns
    dates.py                   # helpers de datas
    stats.py                   # helpers estatísticos (média, desvio, MAD etc.)
  features/
    prediction/service.py      # lógica de previsão mensal de despesas
    anomaly/service.py         # lógica de detecção de anomalias
    autocat/service.py         # categorização automática
    savings/service.py         # recomendações de economia
    cashflow/service.py        # insights de fluxo de caixa
models/                        # diretório para arquivos de modelos treinados
```

`main.py` passará a delegar a lógica para esses services, mantendo as Pydantic models e rotas atuais.

---

## 3. Dados Necessários por Endpoint (do Java para o Python)

### 3.1. Monthly Expenses Prediction (`/monthly-expenses-prediction`)

**Entrada atual (mantida):**
- `categoryId?: number`
- `forecastMonths?: number`
- `historicalTransactions: AiTransaction[]`
  - `type: 'INCOME' | 'EXPENSE'`
  - `date: string (ISO)`
  - `amount: number`
  - `categoryId?: number`
  - `categoryCode?: string`

**Melhoria de uso de dados:**
- Java `budget-api` deve enviar **histórico de pelo menos 6–12 meses** de transações do usuário.
- Python agregará essas transações por mês (e opcionalmente por categoria) para formar uma série temporal.

### 3.2. Anomaly Detection (`/anomaly-detection`)

**Entrada atual (mantida):**
- `transactions: AiTransaction[]` (focamos em `type === 'EXPENSE'`).
- `sensitivity?: number` (limiar de sensibilidade).

**Melhoria de uso de dados:**
- Java envia as últimas N transações (ex.: 3–6 meses) com `transactionId`, `amount`, `date`, `categoryId`, `categoryCode`, `description`.
- Python calcula estatísticas globais e (futuramente) por categoria para detectar outliers.

### 3.3. Auto Categorize (`/auto-categorize`)

**Entrada atual (mantida):**
- `expenses: { expenseId?, description?, amount, paymentMethodId? }[]`

**Melhoria planejada:**
- Em versões futuras, Java poderá expor também um endpoint de **treinamento** (interno) para enviar histórico categorizado, mas o contrato de `/auto-categorize` permanece o mesmo.

### 3.4. Savings Recommendations (`/savings-recommendations`)

**Entrada atual (mantida):**
- `savingsGoalAmount?: number`
- `targetDate?: string`

**Possível enriquecimento futuro (opcional, sem quebrar contrato):**
- Adicionar ao body JSON um bloco opcional, ex.: `historicalSummary`, com:
  - renda média mensal,
  - despesas médias por categoria,
  - saldo médio mensal.
- Python usará se presente; caso contrário, cai num modo mais genérico.

### 3.5. Cashflow Insights (`/cashflow-insights`)

**Entrada atual (mantida):**
- `months?: number` (janela futura a ser projetada).

**Integração planejada:**
- O Java `budget-api` continua responsável por **buscar os dados brutos** de receitas e despesas no PostgreSQL.
- Em uma fase futura, podemos adicionar um endpoint interno em Python para receber o histórico (similar a previsão mensal) e gerar projeções mais precisas. Por ora, usamos um modelo simplificado baseado em parâmetros fixos e, depois, em histórico enviado pelo Java.

---

## 4. Abordagem Estatística / ML (MVP Realista)

### 4.1. Previsão Mensal de Despesas

- **Primeiro passo:**
  - Agregar transações por mês (`YYYY-MM`) para o usuário (e categoria, se `categoryId` for preenchido).
  - Calcular média dos últimos N meses e usar isso como baseline, junto de um simples cálculo de tendência (slope).
- **Evolução:**
  - Usar `scikit-learn` para um modelo de regressão (ex.: `RandomForestRegressor` ou `GradientBoostingRegressor`) com features:
    - mês do ano (1–12),
    - valor do mês passado,
    - média móvel de 3/6/12 meses,
    - desvio-padrão histórico.
  - Opcionalmente, usar `Prophet` ou `statsmodels` para sazonalidade mais avançada.

### 4.2. Detecção de Anomalias

- **Fase 1 (já parcialmente feita):**
  - Z-score ou score normalizado simples com média e desvio padrão globais.
- **Fase 2:**
  - Substituir/estender com **MAD (Median Absolute Deviation)** para ser mais robusto contra outliers.
  - Adicionar por-categoria: manter estatísticas separadas para cada `categoryId` com dados suficientes.
- **Fase 3 (opcional):**
  - Implementar `IsolationForest` (`sklearn.ensemble.IsolationForest`) usando features como `amount`, `log(amount)`, categoria, mês, dia da semana.

### 4.3. Auto Categorização

- **MVP avançado:**
  - Criar um pipeline `scikit-learn` com:
    - `TfidfVectorizer` para `description` (português, com stopwords básicas),
    - Classificador (`LogisticRegression` ou `LinearSVC`) para prever `categoryId` ou `categoryCode`.
  - Usar dados históricos de todas as despesas categorizadas (global) como treino.
  - No futuro, permitir modelo por usuário quando ele tiver dados suficientes.

### 4.4. Recomendações de Economia

- **Regra de negócio + estatística simples:**
  - A partir das médias mensais por categoria (vindas do Java ou calculadas numa etapa de treinamento), identificar:
    - categorias com alto gasto médio e alta variabilidade,
    - categorias "essenciais" vs "ajustáveis".
  - Distribuir o valor de `savingsGoalAmount` ao longo das categorias ajustáveis, gerando ações concretas ("reduzir alimentação fora em X%", etc.).

### 4.5. Insights de Fluxo de Caixa

- Calcular **saldos projetados** mês a mês usando:
  - Receita média anual + tendência,
  - Despesa média anual + tendência (podendo reutilizar lógica da previsão mensal).
- Gerar mensagens de insight baseadas em:
  - quantidade de meses com `status = 'deficit'`,
  - média do saldo projetado,
  - variação mês a mês.

---

## 5. Versionamento de Modelos e Armazenamento

### 5.1. Estratégia de Versão

- Definir versões lógicas por feature:
  - `prediction_v1`, `anomaly_v1`, `autocat_v1`, `savings_v1`, `cashflow_v1`.
- Manter a versão apenas internamente (logs, nomes de arquivos). não alterar o contrato de resposta.

### 5.2. Armazenamento em Disco (Inicial)

- Diretório padrão: `./models` (configurável por `AI_MODEL_DIR`).
- Estrutura sugerida:

```text
models/
  prediction/
    v1/
      global.pkl
      user/{user_id}.pkl
  anomaly/
    v1/
      global.pkl
      user/{user_id}.pkl
  autocat/
    v1/
      global.pkl
      user/{user_id}.pkl
  savings/
    v1/
      config.json
  cashflow/
    v1/
      user/{user_id}.pkl
```

- `models_registry.py` será responsável por:
  - Resolver o caminho de cada modelo (por feature + versão + user/global).
  - Criar diretórios se necessário.
  - Fazer load/save (por exemplo, com `joblib`.

### 5.3. Per-User vs Global

- `prediction` e `cashflow`: preferencialmente **modelo por usuário**, com fallback global/baseline para pouca amostra.
- `anomaly`: per-user quando muitos dados; global + estatísticas robustas para iniciantes.
- `autocat`: modelo global como padrão; per-user opcional no futuro.
- `savings`: majoritariamente regra de negócio, sem necessidade de modelo pesado.

---

## 6. Treinamento, Atualização e Reuso

### 6.1. Treino On-Demand (MVP)

- Quando o endpoint for chamado e não houver modelo para o user:
  - Se houver dados suficientes no request (`historicalTransactions`, etc.),
    - treinamos rapidamente um modelo leve,
    - salvamos no `models/` via `models_registry`,
    - usamos imediatamente para prever.
  - Caso contrário, usamos a lógica baseline atual (média simples, heurísticas).

### 6.2. Evolução Futuras

- Adicionar endpoints internos protegidos (ex.: `/internal/ai/train/...`) para:
  - serem chamados periodicamente pelo `budget-api` (cron/agenda),
  - treinar/atualizar modelos em batch com dados do banco.
- Considerar uso de cache em memória (LRU) para modelos carregados com frequência.

---

## 7. Compatibilidade com Backend Java e Frontend

- **Não alterar** os contratos atuais de request/response das rotas do FastAPI.
- Todo enriquecimento de resposta deve usar campos opcionais já existentes (`historicalAverage`, `trend`, `summaryText`, `modelAccuracy`, etc.).
- Garantir que valores retornados sejam:
  - não negativos para despesas,
  - coerentes (sem explosões numéricas),
  - com `confidence` sempre entre `0.0` e `1.0`.
- Java continuará:
  - extraindo o `userId` a partir do token JWT,
  - chamando o Python com o Bearer token no header (já implementado),
  - montando os DTOs conforme os contratos atuais.

---

## 8. Roadmap de Implementação (Python)

1. **Refatorar estrutura**: criar pastas `core/`, `utils/`, `features/` e mover a lógica de `main.py` para services (sem mudar endpoints).
2. **Adicionar dependências** em `requirements.txt`:
   - `numpy`, `pandas`, `scikit-learn` (e opcionalmente `statsmodels` ou `prophet`).
3. **Implementar `models_registry`** com leitura/escrita de arquivos de modelo (joblib/pickle) e cache simples.
4. **Implementar MVP aprimorado** para:
   - previsão mensal (baseado em média/trend por mês),
   - anomalias (MAD e thresholds melhorados),
   - auto-categorização (heurísticas + placeholder para modelo TF-IDF).
5. **Conectar `main.py`** aos novos services via funções (`predict_monthly_expenses`, `detect_anomalies`, etc.).
6. **Adicionar logs estruturados** (userId, feature, versão) para monitorar comportamentos dos modelos.
7. **Iterar**: quando estável, introduzir o uso real de `scikit-learn`/`Prophet` nos services, mantendo sempre um fallback baseline.

---

## 9. Implementation plan and limitations

Implementation plan (priority 1..5)
1. Add an auth dependency to extract userId from the Authorization Bearer token (FastAPI dependency).
   - File to create: app/core/auth.py (or modify main.py) with get_current_user_id(Depends).
   - Use python-jose or PyJWT; require a secret or public key and algorithm (HS256/RS256).
2. Create project skeleton (app/core, app/utils, app/features/*) and stub services:
   - app/features/prediction/service.py with predict_monthly_expenses(user_id, req).
   - app/features/anomaly/service.py, app/features/autocat/service.py, etc.
3. Implement models_registry.py (app/core/models_registry.py) to manage model paths and simple joblib load/save.
4. Wire routes in main.py to call feature services using user_id = Depends(get_current_user_id).
5. Add requirements.txt and simple unit tests for auth and service stubs; add a CI job to run lint/tests.

Required inputs from the team
- JWT format: which claim holds the user id ("userId" or "sub") and whether it is numeric or string.
- JWT algorithm and verification key/secret (HS256 secret or RS256 public key) — for secure verification, provide public key or KMS path.
- Preferred Python version and dependency constraints (e.g., use poetry/pip/venv).
- Acceptance criteria for MVP (minimal datasets, expected response fields).

My limitations (what I cannot do)
- I cannot run, test, or deploy code in your environment; I provide code and instructions only.
- I cannot access secrets/keys or the running JWT issuer — you must provide keys or configure environment variables.
- I cannot push commits to your repository; you'll need to merge the changes I provide.
- I cannot validate runtime behavior against real tokens or databases; integration testing must be done in your environment.
- If you need production-grade security (key rotation, JWKS discovery, OIDC), you'll need to supply endpoints/config and additional design choices.

Estimated rough effort (MVP)
- Auth dependency + route wiring + basic stubs: 1–2 days.
- models_registry + simple local model save/load + tests: 1–2 days.
- Feature MVP implementations (baseline heuristics): 2–4 days (per feature, parallelizable).
- Integration tests + CI + docs: 1–2 days.

Next actions I can take for you (pick one)
- Generate the FastAPI auth dependency file (app/core/auth.py) and show how to wire it to existing routes.
- Create skeleton files for features and models_registry with minimal stub implementations.
- Produce unit tests for the auth dependency and a sample route.

Please tell me which next action you want and provide JWT verification details (claim name and algorithm + secret/public key location).

## 10. Current features inventory (app/features)

This section was revised to use a test-driven re-evaluation policy: any feature that has unit/integration/e2e tests covering its logic or its endpoints should be considered "Implemented". Partial test coverage => "Partially implemented". No tests => "Stub" or "Missing".

Quick rule (applies to your repo review)
- Implemented: there is at least one test file that imports or exercises the feature code or the endpoint.
- Partially implemented: tests exist but cover only helper logic, not endpoint wiring or edge cases.
- Stub/Missing: no tests and only placeholder code or no folder at all.

Quick commands to detect tests (run in repo root)
- List tests that reference a feature folder:
  - grep -R --line-number "app/features/prediction" tests || true
  - grep -R --line-number "prediction" tests || true
- Run pytest to show which tests fail/cover features:
  - pytest -q -k prediction || true
- List test files:
  - find tests -name "*prediction*.py" -o -name "*anomaly*.py" || true

How to finalize statuses
1. Run the grep/find commands above and note test file paths.
2. For each feature below, paste the matching test files into "Tests" and update "Status" accordingly.
3. Fill "Actual files / functions" with exact module/function names found (e.g., app/features/prediction/service.py -> predict_monthly_expenses).

Template per feature (fill in from repo):

10.1 prediction
- Status: (Implemented / Partially implemented / Stub / Missing) — mark Implemented if tests reference prediction logic or endpoint.
- Actual files / functions: (e.g., app/features/prediction/service.py -> predict_monthly_expenses)
- Endpoint(s) used: POST /api/v1/ai/monthly-expenses-prediction
- Inputs expected: { historicalTransactions, categoryId?, forecastMonths? } (user id must be taken from JWT)
- Outputs produced: { monthlyForecast: [...], summary: {...}, confidence? }
- Tests: (list test files, e.g., tests/features/test_prediction_service.py)
- Known limitations:
  - currently uses simple monthly aggregation + baseline trend
- Next tasks (priority):
  1. Confirm function name and wire get_current_user_id dependency.
  2. Add unit tests for edge cases not covered yet.
  3. Add models_registry usage and per-user model fallback if missing.

10.2 anomaly
- Status: (Implemented / Partially implemented / Stub / Missing)
- Actual files / functions: (e.g., app/features/anomaly/service.py -> detect_anomalies)
- Endpoint(s) used: POST /api/v1/ai/anomaly-detection
- Inputs expected: { transactions[], sensitivity? } (user id from JWT)
- Outputs produced: { anomalies: [{ transactionId, score, reason }], stats: {...} }
- Tests: (list test files)
- Known limitations:
  - current algorithm: simple z-score; not robust to skewed distributions
- Next tasks (priority):
  1. Switch to MAD scoring and add per-category stats.
  2. Add tests that cover edge cases (single-value series, zero variance).

10.3 autocat (auto-categorization)
- Status: (Implemented / Partially implemented / Stub / Missing)
- Actual files / functions: (e.g., app/features/autocat/service.py -> auto_categorize)
- Endpoint(s) used: POST /api/v1/ai/auto-categorize
- Inputs expected: { expenses: [{ expenseId?, description?, amount, paymentMethodId? }] } (user id from JWT)
- Outputs produced: { categorized: [{ expenseId?, categoryId, probability? }], modelVersion? }
- Tests: (list test files)
- Known limitations:
  - currently uses heuristic matching / placeholder model (or note real implementação)
- Next tasks (priority):
  1. If tests are missing for endpoint wiring, add integration tests exercising the endpoint payload.
  2. Add training/evaluation tests for TF-IDF pipeline when introduced.

10.4 savings
- Status: (Implemented / Partially implemented / Stub / Missing)
- Actual files / functions: (e.g., app/features/savings/service.py -> savings_recommendations)
- Endpoint(s) used: POST /api/v1/ai/savings-recommendations
- Inputs expected: { savingsGoalAmount?, targetDate?, optional historicalSummary? } (user id from JWT)
- Outputs produced: { plan: [{ categoryId, suggestedReduction, impact }], timeline, confidence }
- Tests: (list test files)
- Known limitations:
  - Mostly rule-based; needs category importance classification and variability measures
- Next tasks (priority):
  1. Add use of historicalSummary when provided.
  2. Add simulated scenarios and unit tests for recommendations.

10.5 cashflow
- Status: (Implemented / Partially implemented / Stub / Missing)
- Actual files / functions: (e.g., app/features/cashflow/service.py -> cashflow_insights)
- Endpoint(s) used: POST /api/v1/ai/cashflow-insights
- Inputs expected: { months? } (user id from JWT)
- Outputs produced: { projections: [{ month, balance }], insights: [string], riskScore }
- Tests: (list test files)
- Known limitations:
  - projection model is simplified; no per-user trained model persisted yet
- Next tasks (priority):
  1. Reuse prediction logic for projected despesas.
  2. Add scenario stress tests and unit tests.

10.6 cross-feature items (shared concerns)
- Auth: Features must extract userId from the JWT (do not rely on body-provided userId). If tests prove auth wiring exists, mark auth as implemented.
- models_registry: confirm presence and shape (app/core/models_registry.py). If tests cover persistence/load, mark implemented.
- Logging: ensure tests or code assertions validate structured logs include userId, feature name and model/version when required.
- Tests: prefer adding small smoke tests that call each route with a test JWT and assert non-error responses and expected keys.
- CI: ensure CI runs pytest and fails on regressions (mark implemented if current CI config does this).

10.7 How to convert this template into concrete documentation quickly
- Run: ls app/features and replace "Actual files / functions" with real filenames and exported functions.
- Run greps above to collect test filenames and paste them into the "Tests" field.
- Mark features with tests as Implemented. For partial coverage, mark Partially implemented and list missing tests as TODO.

If you want, I can:
- Parse a list of test files you paste here and auto-fill the "Tests" and set Status values.
- Or, if you allow, I can generate the grep output command set you can run locally and then feed me the results so I auto-complete the inventory.

---