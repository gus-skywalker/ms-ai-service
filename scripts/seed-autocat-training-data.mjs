#!/usr/bin/env node

let API_BASE_URL = (process.env.API_BASE_URL || "http://localhost:8080").replace(/\/+$/, "");
const AUTH_TOKEN = process.env.AUTH_TOKEN || "";
const WORKSPACE_ID = (process.env.WORKSPACE_ID || "").replace(/\s+/g, "");
const ACCOUNT_ID = process.env.ACCOUNT_ID || "";
const DRY_RUN = process.env.DRY_RUN === "1" || process.env.DRY_RUN === "true";

const REQUIRED_CATEGORY_ALIASES = {
  groceries: ["groceries", "supermarket", "supermercado", "mercado", "alimentacao", "alimentação", "food"],
  transportation: ["transportation", "transport", "transporte", "mobilidade"],
  subscriptions: ["subscriptions", "subscription", "assinaturas", "assinatura", "recorrentes"],
  health: ["health", "healthcare", "pharmacy", "farmacia", "farmácia", "saude", "saúde"],
  restaurants: ["restaurants", "restaurant", "restaurante", "alimentacao-fora", "delivery", "dining out", "dining_out"],
};

const TRAINING_EXPENSES = [
  ["2025-10-03", 142.35, "Mercado Extra compra da semana", "groceries"],
  ["2025-10-09", 87.42, "Supermercado Pao de Acucar", "groceries"],
  ["2025-10-18", 213.90, "Atacadao alimentos", "groceries"],
  ["2025-11-04", 96.10, "Carrefour mercado", "groceries"],
  ["2025-11-19", 54.75, "Hortifruti frutas e verduras", "groceries"],

  ["2025-10-05", 31.20, "Uber viagem centro", "transportation"],
  ["2025-10-12", 27.80, "99 Taxi corrida", "transportation"],
  ["2025-10-23", 8.80, "Metro bilhete unico", "transportation"],
  ["2025-11-08", 44.50, "Uber aeroporto", "transportation"],
  ["2025-11-22", 19.90, "Estacionamento shopping", "transportation"],

  ["2025-10-02", 39.90, "Netflix assinatura mensal", "subscriptions"],
  ["2025-10-06", 21.90, "Spotify mensalidade", "subscriptions"],
  ["2025-10-14", 14.90, "Amazon Prime assinatura", "subscriptions"],
  ["2025-11-02", 39.90, "Netflix streaming", "subscriptions"],
  ["2025-11-15", 29.90, "iCloud armazenamento", "subscriptions"],

  ["2025-10-07", 46.20, "Drogaria Sao Paulo remedios", "health"],
  ["2025-10-16", 62.40, "Droga Raia farmacia", "health"],
  ["2025-10-29", 118.00, "Consulta laboratorio exame", "health"],
  ["2025-11-11", 35.70, "Pague Menos farmacia", "health"],
  ["2025-11-25", 74.80, "Drogasil medicamentos", "health"],

  ["2025-10-04", 54.00, "Restaurante almoco", "restaurants"],
  ["2025-10-11", 71.30, "Ifood jantar", "restaurants"],
  ["2025-10-20", 18.50, "Padaria cafe da manha", "restaurants"],
  ["2025-11-06", 83.10, "Outback jantar", "restaurants"],
  ["2025-11-17", 42.90, "Lanchonete lanche", "restaurants"],
];

function usage() {
  console.log(`
Seed de treino para auto-categorizacao.

Variaveis obrigatorias:
  AUTH_TOKEN=<jwt do usuario>
  WORKSPACE_ID=<workspace uuid>

Variaveis opcionais:
  API_BASE_URL=http://localhost:8080
  ACCOUNT_ID=<financial account uuid; se omitido usa a primeira conta financeira>
  DRY_RUN=1

Exemplo:
  AUTH_TOKEN='...' WORKSPACE_ID='...' node scripts/seed-autocat-training-data.mjs
`);
}

function normalize(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function headers() {
  return {
    "Authorization": `Bearer ${AUTH_TOKEN}`,
    "X-Workspace-Id": WORKSPACE_ID,
    "Content-Type": "application/json",
  };
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...headers(),
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  if (text.trim().startsWith("<")) {
    throw new Error(`${options.method || "GET"} ${API_BASE_URL}${path} returned HTML instead of JSON. Check API_BASE_URL; budget-api usually runs at http://localhost:8080/api.`);
  }
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(`${options.method || "GET"} ${path} failed: ${response.status} ${JSON.stringify(body)}`);
  }
  return body;
}

async function requestWithApiFallback(path, options = {}) {
  try {
    return await request(path, options);
  } catch (error) {
    const message = String(error?.message || "");
    if (!API_BASE_URL.endsWith("/api") && message.includes("returned HTML instead of JSON")) {
      API_BASE_URL = `${API_BASE_URL}/api`;
      console.log(`API_BASE_URL ajustado automaticamente para ${API_BASE_URL}`);
      return request(path, options);
    }
    throw error;
  }
}

function findCategory(categories, key) {
  const aliases = REQUIRED_CATEGORY_ALIASES[key].map(normalize);
  return categories.find((category) => {
    if (category.active === false) return false;
    if (category.type && String(category.type).toUpperCase() !== "EXPENSE") return false;
    const values = [category.code, category.name].map(normalize);
    return values.some((value) => aliases.some((alias) => value === alias || value.includes(alias)));
  });
}

async function main() {
  if (!AUTH_TOKEN || !WORKSPACE_ID) {
    usage();
    process.exit(1);
  }

  let accountId = ACCOUNT_ID;
  if (!accountId) {
    const accounts = await requestWithApiFallback("/accounts");
    if (!Array.isArray(accounts) || accounts.length === 0) {
      throw new Error("Nenhuma conta financeira encontrada em /accounts. Informe ACCOUNT_ID manualmente.");
    }
    const mainAccount = accounts.find((account) => normalize(account.name).includes("main account")) || accounts[0];
    accountId = mainAccount.id;
    console.log(`Conta financeira selecionada: ${mainAccount.id} ${mainAccount.name || ""} ${mainAccount.currency || ""}`.trim());
  }

  const categories = await requestWithApiFallback("/categories");
  const categoryByKey = {};
  const missing = [];

  for (const key of Object.keys(REQUIRED_CATEGORY_ALIASES)) {
    const category = findCategory(categories, key);
    if (!category) {
      missing.push(key);
    } else {
      categoryByKey[key] = category;
    }
  }

  if (missing.length) {
    console.error("Nao encontrei categorias compatíveis para:", missing.join(", "));
    console.error("Categorias EXPENSE ativas disponiveis:");
    for (const category of categories.filter((item) => item.active !== false && (!item.type || String(item.type).toUpperCase() === "EXPENSE"))) {
      console.error(`- id=${category.id} code=${category.code} name=${category.name}`);
    }
    process.exit(1);
  }

  console.log("Categorias resolvidas:");
  for (const [key, category] of Object.entries(categoryByKey)) {
    console.log(`- ${key}: ${category.id} ${category.code} (${category.name})`);
  }

  if (DRY_RUN) {
    console.log(`DRY_RUN ativo. ${TRAINING_EXPENSES.length} transacoes seriam criadas.`);
    return;
  }

  let created = 0;
  for (const [date, amount, description, categoryKey] of TRAINING_EXPENSES) {
    const category = categoryByKey[categoryKey];
    const payload = {
      transactionDate: date,
      description,
      source: "MANUAL",
      status: "POSTED",
      visibilityScope: "WORKSPACE",
      idempotencyKey: `autocat-training:${WORKSPACE_ID}:${date}:${normalize(description)}`,
      entries: [
        {
          accountId,
          direction: "OUTFLOW",
          amount,
          categoryId: category.id,
          paymentMethodName: "Seed treino IA",
          categorizationSource: "USER",
          categorizationReason: "Seed manual para treino do auto-categorizador",
        },
      ],
    };
    const result = await requestWithApiFallback("/transactions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    created += 1;
    console.log(`created ${created}/${TRAINING_EXPENSES.length}: ${result.id || description}`);
  }

  console.log(`Seed concluido: ${created} transacoes categorizadas criadas.`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
