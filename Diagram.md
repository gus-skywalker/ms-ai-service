flowchart LR
subgraph JavaBackend["budget-api (Java)"]
A[User actions / DB changes\n(transactions, categories)] --> B[Event Producer]
B -->|HTTP / Message| C[Sync Trigger]
B --> Kafka[Optional: Kafka/RabbitMQ]
end

subgraph PythonAI["ai-service (Python)"]
direction TB
C --> D[Ingress (HTTP Internal) / Queue Consumer]
D --> E[Preprocessor & Aggregator]
E --> F[Feature Store / Cache\nstorage/user_data/{userId}/...]
F --> G[Models Registry / models/]
G --> H[Trainers (on sync)]
F --> I[Services (cashflow, savings, prediction, anomaly, autocat)]
I --> J[Public API endpoints\n/api/v1/ai/* ]
H --> G
end

subgraph Clients["Clients"]
UserFrontend --> JavaBackend
ThirdPartyTools --> JavaBackend
end

JavaBackend -- "POST /internal/ai/sync-user-data (raw or aggregated JSON) + auth" --> PythonAI
Kafka --> D
PythonAI -->|fast responses| JavaBackend
