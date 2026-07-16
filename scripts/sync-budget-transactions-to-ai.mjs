#!/usr/bin/env node

let API_BASE_URL = (process.env.API_BASE_URL || "http://localhost:8080/api").replace(/\/+$/, "");
const AI_BASE_URL = (process.env.AI_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
const AUTH_TOKEN = process.env.AUTH_TOKEN || "";
const WORKSPACE_ID = (process.env.WORKSPACE_ID || "").replace(/\s+/g, "");
const AI_SERVICE_TOKEN = process.env.AI_SERVICE_TOKEN || "testtoken";
const DRY_RUN = process.env.DRY_RUN === "1" || process.env.DRY_RUN === "true";

function usage() {
  console.log(`
Sincroniza transacoes atuais do budget-api para o feature store do ai-service.

Variaveis obrigatorias:
  AUTH_TOKEN=<jwt do usuario>
  WORKSPACE_ID=<workspace uuid>

Variaveis opcionais:
  API_BASE_URL=http://localhost:8080/api
  AI_BASE_URL=http://localhost:8000
  AI_SERVICE_TOKEN=testtoken
  DRY_RUN=1

Exemplo:
  AUTH_TOKEN='...' WORKSPACE_ID='...' node scripts/sync-budget-transactions-to-ai.mjs
`);
}

async function budgetRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Authorization": `Bearer ${AUTH_TOKEN}`,
      "X-Workspace-Id": WORKSPACE_ID,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  if (text.trim().startsWith("<")) {
    throw new Error(`${API_BASE_URL}${path} returned HTML instead of JSON. Use API_BASE_URL=http://localhost:8080/api.`);
  }
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(`${options.method || "GET"} ${path} failed: ${response.status} ${JSON.stringify(body)}`);
  }
  return body;
}

async function aiRequest(path, options = {}) {
  const response = await fetch(`${AI_BASE_URL}${path}`, {
    ...options,
    headers: {
      "X-Service-Token": AI_SERVICE_TOKEN,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(`${options.method || "GET"} ${path} failed: ${response.status} ${JSON.stringify(body)}`);
  }
  return body;
}

async function fetchAllTransactions() {
  const limit = 200;
  let offset = 0;
  const items = [];
  while (true) {
    const page = await budgetRequest(`/transactions?limit=${limit}&offset=${offset}`);
    const pageItems = page?.items || [];
    items.push(...pageItems);
    offset += pageItems.length;
    if (!pageItems.length || offset >= Number(page?.total || 0)) {
      break;
    }
  }
  return items;
}

function toAiTransaction(transaction) {
  const direction = String(transaction.direction || "").toUpperCase();
  return {
    transactionId: transaction.id,
    userId: WORKSPACE_ID,
    type: direction === "INFLOW" ? "INCOME" : "EXPENSE",
    date: transaction.date,
    amount: Math.abs(Number(transaction.amount || 0)),
    currency: "BRL",
    categoryId: transaction.categoryId ?? null,
    categoryCode: transaction.categoryCode ?? null,
    description: transaction.description || "",
    paymentMethodId: transaction.paymentMethodId ?? null,
  };
}

async function main() {
  if (!AUTH_TOKEN || !WORKSPACE_ID) {
    usage();
    process.exit(1);
  }

  const transactions = await fetchAllTransactions();
  const rawTransactions = transactions
    .filter((transaction) => String(transaction.status || "POSTED").toUpperCase() !== "CANCELLED")
    .map(toAiTransaction);

  const categorized = rawTransactions.filter((transaction) => transaction.categoryId != null).length;
  console.log(`Transacoes lidas: ${transactions.length}`);
  console.log(`Transacoes enviaveis: ${rawTransactions.length}`);
  console.log(`Transacoes categorizadas: ${categorized}`);

  if (DRY_RUN) {
    console.log("DRY_RUN ativo. Nada foi enviado ao ai-service.");
    return;
  }

  const payload = {
    userId: WORKSPACE_ID,
    mode: "full",
    syncType: "full",
    source: "budget-api-retro-sync",
    timestamp: new Date().toISOString(),
    rawTransactions,
  };
  const result = await aiRequest("/internal/ai/sync-user-data", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  console.log("Sync concluido:", JSON.stringify(result));
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
