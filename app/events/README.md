# Event Publisher - MembershipCreated

Implementação do publisher do evento `MembershipCreated` seguindo os requisitos da **FASE 3 - IMPLEMENTAÇÃO GUIADA**.

## ✅ Requisitos Implementados

### 1. Emissão Apenas Após Commit
- ✓ O publisher é chamado **após** o commit da transação
- ✓ Garante consistência entre banco de dados e eventos
- ✓ Evita eventos para dados não persistidos

### 2. Payload Contém Apenas IDs (Sem PII)
- ✓ `membershipId`: ID da membership
- ✓ `userId`: ID do usuário
- ✓ `budgetId`: ID do budget
- ✓ `role`: Papel do membro (ex: "owner", "member")
- ✓ **Nenhum dado pessoal** (nome, email, telefone)

### 3. Metadados Obrigatórios
- ✓ `eventVersion`: Versão do schema do evento ("1.0.0")
- ✓ `correlationId`: ID de correlação para rastreamento
- ✓ `actor`: ID do ator que disparou a ação
- ✓ `timestamp`: ISO 8601 timestamp do evento

### 4. Não Enriquece com Dados Externos
- ✓ Publisher não faz consultas externas
- ✓ Publisher não adiciona dados além do payload fornecido
- ✓ Evento permanece imutável após criação

### 5. Não Acopla Consumidor
- ✓ Eventos publicados em Redis Streams
- ✓ Publisher não conhece ou depende de consumidores
- ✓ Consumidores podem se inscrever independentemente

### 6. Características Adicionais
- ✓ **Idempotência**: Eventos duplicados são detectados via `correlationId`
- ✓ **Auditoria**: Todos os eventos são persistidos no Redis Stream
- ✓ **TTL**: Chave de idempotência expira em 7 dias
- ✓ **Imutabilidade**: Eventos são frozen (não modificáveis)
- ✓ **Out-of-order**: Aceita eventos fora de ordem
- ✓ **Reprocessamento**: Seguro para reprocessar

## 📁 Estrutura de Arquivos

```
app/events/
├── __init__.py              # Package initialization
├── base.py                  # BaseEvent - classe base para todos os eventos
├── membership_events.py     # MembershipCreated event definition
├── publisher.py             # EventPublisher - publicador de eventos
└── usage_example.py         # Exemplos de uso correto

tests/
└── test_event_publisher.py  # Testes completos (13 testes, 100% pass)
```

## 🚀 Uso Básico

```python
from app.events.membership_events import MembershipCreated
from app.events.publisher import get_publisher

# 1. Realizar operações no banco
membership_id = save_membership(user_id, budget_id, role)

# 2. COMMIT da transação
db.session.commit()

# 3. APENAS após commit, publicar evento
event = MembershipCreated(
    membershipId=membership_id,
    userId=user_id,
    budgetId=budget_id,
    role=role,
    actor=current_user_id,
    correlationId=request_correlation_id
)

publisher = get_publisher()
publisher.publish(event)
```

## 🔒 Garantias de Segurança

### Compliance (LGPD/GDPR)
- ✅ Nenhum PII nos eventos
- ✅ Apenas IDs são propagados
- ✅ Dados sensíveis fluem apenas via REST autenticado

### Idempotência
- ✅ Mesmo `correlationId` = mesmo evento
- ✅ Reprocessamento seguro
- ✅ Sem duplicatas

### Auditoria
- ✅ Todos os eventos registrados
- ✅ Timestamp preciso
- ✅ Actor identificado
- ✅ Rastreabilidade via correlationId

## 📊 Event Schema

### MembershipCreated Event

```json
{
  "eventType": "MembershipCreated",
  "eventVersion": "1.0.0",
  "correlationId": "550e8400-e29b-41d4-a716-446655440000",
  "actor": "user-123",
  "timestamp": "2026-01-23T18:30:00.000Z",
  "membershipId": "membership-abc-123",
  "userId": "user-def-456",
  "budgetId": "budget-ghi-789",
  "role": "owner"
}
```

### Campos

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|------------|-----------|
| `eventType` | string | Sim | Sempre "MembershipCreated" |
| `eventVersion` | string | Sim | Versão do schema (1.0.0) |
| `correlationId` | string | Sim | ID de correlação (UUID) |
| `actor` | string | Sim | ID do usuário/sistema que disparou |
| `timestamp` | string | Sim | ISO 8601 timestamp UTC |
| `membershipId` | string | Sim | ID da membership criada |
| `userId` | string | Sim | ID do usuário membro |
| `budgetId` | string | Sim | ID do budget |
| `role` | string | Sim | Papel do membro |

## 🧪 Testes

Todos os 13 testes passando:

```bash
pytest tests/test_event_publisher.py -v
```

### Cobertura de Testes

- ✅ Criação de evento com campos obrigatórios
- ✅ Geração automática de correlationId
- ✅ Geração automática de timestamp
- ✅ Imutabilidade de eventos
- ✅ Ausência de PII
- ✅ Publicação bem-sucedida
- ✅ Idempotência (prevenção de duplicatas)
- ✅ Inclusão de metadados obrigatórios
- ✅ TTL da chave de idempotência
- ✅ Múltiplos eventos com IDs diferentes
- ✅ Limitação de tamanho do stream
- ✅ Eventos fora de ordem
- ✅ Não enriquecimento com dados externos

## 🔧 Configuração

### Variáveis de Ambiente

```bash
REDIS_URL=redis://localhost:6379/0  # URL do Redis
```

### Dependências

```text
redis>=5.0.0
pydantic>=2.0.0
```

## 📝 Redis Streams

### Stream Principal

- **Nome**: `domain:events`
- **Formato**: Redis Stream (XADD)
- **Retenção**: Últimos 10.000 eventos (configurável)

### Chaves de Idempotência

- **Padrão**: `events:processed:{correlationId}`
- **TTL**: 7 dias
- **Propósito**: Detectar duplicatas

## ⚠️ Importantes Considerações

### ✅ FAÇA

1. Sempre publique eventos **após** commit bem-sucedido
2. Use IDs únicos para `correlationId`
3. Propague `correlationId` de requisições HTTP
4. Inclua `actor` para auditoria
5. Trate erros de publicação (log/alert)

### ❌ NÃO FAÇA

1. **NÃO** publique eventos antes do commit
2. **NÃO** inclua PII (nomes, emails, telefones)
3. **NÃO** enriqueça eventos com dados externos
4. **NÃO** assuma processamento síncrono
5. **NÃO** acople lógica de consumidores

## 🏗️ Arquitetura

```
┌─────────────┐
│ budget-api  │
│   Service   │
└──────┬──────┘
       │
       │ 1. DB Operations
       │ 2. COMMIT
       │ 3. Publish Event
       ▼
┌─────────────┐
│   Event     │
│  Publisher  │
└──────┬──────┘
       │
       │ XADD to stream
       ▼
┌─────────────┐
│   Redis     │
│  Streams    │
└──────┬──────┘
       │
       │ Multiple consumers
       ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ payment-api │  │   ai-svc    │  │   others    │
└─────────────┘  └─────────────┘  └─────────────┘
```

## 🔄 Fluxo de Eventos

1. **Trigger**: Ação do usuário (criar membership)
2. **Transaction**: Operações de banco de dados
3. **Commit**: Persistência dos dados
4. **Event Creation**: Criação do evento com apenas IDs
5. **Idempotency Check**: Verificação se já foi publicado
6. **Publish**: Publicação no Redis Stream
7. **Mark Processed**: Marcação como processado (TTL 7d)
8. **Consumers**: Consumidores processam assincronamente

## 📚 Exemplos Completos

Veja `app/events/usage_example.py` para exemplos completos de:
- Padrão correto de publicação
- Tratamento de erros
- Idempotência
- Padrões incorretos (anti-patterns)

## 🤝 Integração com Outros Serviços

### payment-api
- Escuta eventos `MembershipCreated`
- Cria customer no Stripe se necessário
- Associa billing ao budget

### ai-service
- Pode escutar para análises
- Não é obrigatório para este evento

### Outros serviços
- Podem se inscrever livremente
- Publisher não conhece consumidores
- Desacoplamento total

## 📈 Monitoramento

### Métricas Recomendadas

- Eventos publicados/segundo
- Taxa de duplicatas (idempotência)
- Latência de publicação
- Falhas de publicação
- Tamanho do stream

### Logs

Todos os eventos de publicação são logados com:
- `correlation_id`
- `event_type`
- `actor`
- `stream`
- `message_id`

## 🔐 Segurança

- ✅ Sem PII em eventos
- ✅ Apenas IDs propagados
- ✅ Auditoria completa
- ✅ Imutabilidade garantida
- ✅ Rastreabilidade via correlationId

## 📖 Referências

- Pydantic v2: https://docs.pydantic.dev/
- Redis Streams: https://redis.io/docs/data-types/streams/
- Event-Driven Architecture
- LGPD/GDPR Compliance
