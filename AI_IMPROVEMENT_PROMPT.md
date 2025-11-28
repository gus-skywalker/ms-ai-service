
1. **Anomalias por categoria e contexto**
   - Calcular baseline de `amount` por `categoryId`/`categoryCode`.
   - Comparar cada despesa com a média/desvio da sua categoria.
   - Opcional: considerar dia da semana, mês, ou outros atributos.

2. **Algoritmos de outlier mais robustos (futuro)**
   - Isolation Forest / Local Outlier Factor sobre features:
     - `amount`, `categoryId`, `dia da semana`, `mês`, histórico recente.
   - Ainda mapear resultado para `AnomalyItem`/`severity` compatíveis.

3. **Summary enriquecido**
   - Incluir no `summaryText` insights por categoria (onde há mais anomalias, potencial de economia etc.).

**Impacto de contrato:**
- Nenhum. Só melhora interna da detecção.

---

### 3. Categorização Automática

**Endpoint:** `POST /api/v1/ai/auto-categorize`

**Contrato atual (Python):**

```python
class AutoCategorizationRequestItem(BaseModel):
    expenseId: Optional[str]
    description: Optional[str]
    amount: float
    paymentMethodId: Optional[int]

class AutoCategorizationRequest(BaseModel):
    expenses: List[AutoCategorizationRequestItem]

class CategorySuggestion(BaseModel):
    id: int
    code: str
    name: str
    confidence: float

class CategorizationSuggestionItem(BaseModel):
    expenseId: Optional[str]
    suggestedCategory: CategorySuggestion
    alternativeCategories: List[CategorySuggestion]
    reasoning: Optional[str]

class AutoCategorizationResponse(BaseModel):
    suggestions: List[CategorizationSuggestionItem]
```

**Regra atual:**
- Heurísticas simples baseadas em `description` (minúsculas):
  - Contém "uber" ou "99" → `transportation` / "Transporte", `confidence = 0.8`.
  - Contém "ifood" ou "rappi" → `dining_out` / "Alimentação Fora", `confidence = 0.85`.
  - Contém "mercado" ou "supermercado" → `groceries` / "Compras", `confidence = 0.9`.
  - Senão → `miscellaneous` / "Outros", `confidence = 0.4`.
- Sempre devolve categoria alternativa `miscellaneous` com `confidence = 1 - confidence_principal`.
- `reasoning` textual explica que foi heurística baseada na descrição.

**Melhorias planejadas:**

1. **Modelo supervisionado por usuário (Naive Bayes / Logistic Regression)**
   - Representar `description` com TF-IDF.
   - Incluir features numéricas: `amount`, `paymentMethodId`, dia do mês.
   - Treinar um modelo por usuário (ou por cluster de usuários) com dados históricos do próprio usuário.

2. **Endpoint de aprendizado supervisionado (novo)**

   ```http
   POST /api/v1/ai/learn-categorization
   Authorization: Bearer {token}
   Content-Type: application/json
   
   {
     "expenses": [
       {
         "description": "Compra supermercado X",
         "amount": 150.00,
         "paymentMethodId": 3,
         "categoryId": 1
       }
     ]
   }
   ```

   - Objetivo: ser chamado pelo `budget-api` quando o usuário confirma/corrige categoria.
   - Python:
     - Atualiza dataset de treino para `user_id`.
     - (Re)treina modelo de categorização para esse usuário.

3. **Fallback inteligente**
   - Se não existir modelo treinado ou poucos exemplos → manter heurísticas atuais.

**Impacto de contrato:**
- `auto-categorize` mantido como está (front/back Java intactos).
- Novo endpoint interno `learn-categorization` para permitir aprendizado contínuo.

---

### 4. Recomendações de Economia

**Endpoint:** `POST /api/v1/ai/savings-recommendations`

**Contrato atual (Python):**

```python
class SavingsRecommendationRequest(BaseModel):
    savingsGoalAmount: Optional[float]
    targetDate: Optional[str]

class SavingsAction(BaseModel):
    id: str
    description: str
    estimatedMonthlyImpact: float
    categoryId: Optional[int]
    difficultyLevel: str
    confidence: float

class SavingsPlan(BaseModel):
    recommendedMonthlySavings: float
    projectedBalanceByTargetDate: float
    probabilityOfSuccess: float
    actions: List[SavingsAction]

class SavingsRecommendationResponse(BaseModel):
    plan: SavingsPlan
    summaryText: Optional[str]
```

**Regra atual:**
- Usa `goal = savingsGoalAmount` ou 200.0 se nulo.
- Gera plano fixo:
  - Uma ação: `reduce_dining_out`, impacto = goal, dificuldade `medium`, `confidence = 0.8`.
  - `recommendedMonthlySavings = goal`.
  - `projectedBalanceByTargetDate = goal * 6`.
  - `probabilityOfSuccess = 0.75`.
  - `summaryText` fixo.

**Melhorias planejadas:**

1. **Basear recomendações em dados reais**
   - Do lado Java, agregar dados por categoria:
     - `currentMonthlyAverage` por categoria.
     - Identificar categorias com maior "excesso" relativamente a benchmarks ou metas do usuário.
   - Enviar opcionalmente um campo estendido (futuro) com esses dados para o endpoint, ex.: `spendingProfile`.

2. **Regras de negócio dinâmicas**
   - Gerar ações múltiplas:
     - Reduzir `dining_out` em X%.
     - Reduzir `subscriptions` em Y%.
     - Evitar compras grandes em `travel` no mês alvo.
   - Calcular `estimatedMonthlyImpact` baseado no histórico do usuário.

3. **Benchmarking anônimo (futuro)**
   - Comparar gastos do usuário com média de usuários similares por categoria.
   - Retornar no plano dados tipo `benchmarkComparison`.

**Impacto de contrato:**
- Nenhum obrigatório; podemos enriquecer o `SavingsRecommendationRequest` no futuro.
- Para agora, só melhorar a qualidade do `plan` com base em dados que o Java pode pré-calcular.

---

### 5. Insights de Fluxo de Caixa

**Endpoint:** `POST /api/v1/ai/cashflow-insights`

**Contrato atual (Python):**

```python
class CashflowInsightsRequest(BaseModel):
    months: int = 6

class CashflowAlert(BaseModel):
    severity: str
    message: str
    suggestions: List[str]

class CashflowForecastItem(BaseModel):
    month: str
    predictedIncome: float
    predictedExpenses: float
    projectedBalance: float
    status: str  # "surplus" | "deficit"
    alert: Optional[CashflowAlert]

class CashflowInsightsResponse(BaseModel):
    currentBalance: float
    forecast: List[CashflowForecastItem]
    averageMonthlyBalance: float
    insights: List[str]
```

**Regra atual:**
- Usa apenas `months` como entrada.
- Simula cenário sintético:
  - `predictedIncome = 5000.0`.
  - `predictedExpenses = 4000.0 + 100 * (i - 1)`.
  - `projectedBalance` = saldo acumulado.
  - `status` e `alert` conforme `net >= 0`.
- `currentBalance = 0.0`.

**Melhorias planejadas:**

1. **Entrada estendida opcional com histórico real**
   - Evoluir o request (mantendo compatibilidade) para aceitar opcionalmente:

   ```json
   {
     "months": 6,
     "historicalCashflow": [
       { "month": "2025-09", "income": 5000.0, "expenses": 4200.0 },
       { "month": "2025-10", "income": 5000.0, "expenses": 3900.0 }
     ]
   }
   ```

   - `historicalCashflow` seria agregado no Java a partir de `Income` + `Expense`.
   - Se presente, Python usa isso para estimar `predictedIncome` e `predictedExpenses` futuras.
   - Se ausente, mantém modo sintético atual (backwards compatible).

2. **Cálculo baseado em previsões de despesas (integração com #1)**
   - Opcional: somar previsões do endpoint `monthly-expenses-prediction` por categoria para estimar `predictedExpenses`.
   - Para `predictedIncome`, usar média móvel das receitas históricas.

3. **Insights mais ricos**
   - Identificar meses com déficit e explicar por categoria.
   - Sugerir ações específicas (ex.: "se reduzir dining_out em R$ X, evita déficit no mês Y").

**Impacto de contrato:**
- Curto prazo: manter apenas `months` e lógica sintética.
- Médio prazo: estender modelo com `historicalCashflow` opcional; ajustar Java para enviar quando pronto.

---

## 🌱 Endpoint Adicional Recomendado

### `POST /api/v1/ai/learn-categorization`

**Objetivo:**
- Permitir que o `budget-api` envie exemplos de despesas rotuladas (categoria confirmada pelo usuário) para que o `ai-service` treine ou ajuste modelos de categorização.

**Request sugerido:**

```http
POST /api/v1/ai/learn-categorization
Authorization: Bearer {token}
Content-Type: application/json

{
  "expenses": [
    {
      "description": "Compra supermercado X",
      "amount": 150.0,
      "paymentMethodId": 3,
      "categoryId": 1
    }
  ]
}
``

**Comportamento esperado:**
- Python agrupando exemplos por `user_id`.
- Atualização de dataset de treino.
- Re-treinamento de modelo Naive Bayes / Logistic Regression para o usuário.
- Persistência dos modelos (ex.: com `joblib`) em disco ou em storage dedicado.

**Impacto de integração:**
- Novo usecase no `budget-api` para enviar correções de categoria.
- Front já captura correções do usuário (ex.: quando muda categoria de uma despesa) e o Java repassa para esse endpoint.

---

## 🧩 Integração Java ↔ Python – Pontos-Chave

1. **Java sempre filtra e enriquece dados**
   - Usa `ExpenseRepository`, `IncomeRepository` etc.
   - Constrói DTOs (`AiTransactionDto`, `AutoCategorizationRequestDto`, `CashflowInsightsRequestDto`...).
   - Chama os clients de IA via `RestClientProvider`.

2. **Python nunca acessa o banco diretamente (no cenário atual)**
   - Recebe dados necessários via JSON.
   - Usa `user_id` do token para qualquer lógica específica por usuário.

3. **Autorização consistente**
   - `RestClientProvider` sempre propaga o JWT do usuário para o `ai-service`.
   - `ai-service` usa JWKS do auth-server para validar.

---

## ✅ Resumo do que já está pronto vs. o que é futuro

**Já pronto (MVP funcional):**
- Endpoints de IA com contratos estáveis.
- Segurança integrada com auth-server.
- Integração Java ↔ Python com token propagado.
- Lógicas baseline de previsão, anomalia, categorização, savings e cashflow.

**Próximos passos de evolução de IA:**
1. Implementar modelos reais no Python para previsão mensal (Prophet/Holt-Winters).
2. Tornar anomalias contexto-sensíveis (por categoria, tempo) e/ou usar Isolation Forest.
3. Criar endpoint `learn-categorization` e implementar modelo de classificação supervisionado por usuário.
4. Enriquecer savings e cashflow com dados reais agregados pelo `budget-api` (ex.: `historicalCashflow`).
5. (Opcional) Adicionar cache e re-treinamento assíncrono (Celery/Redis) no `ai-service`.

Este arquivo deve ser usado como referência/prompt quando formos evoluir o `ai-service` de heurísticas simples para IA mais sofisticada, sem quebrar a integração já estabelecida com o `budget-api` e o front Vue.
