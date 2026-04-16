# RAG ingestion & answer generation — architecture flowchart

High-level flow: sources → preprocess → Pub/Sub → processed storage → RAG ingestor → chunks / embeddings → vector store; separate path from orchestrator through retrieval, rerank, threshold, LLM, to response artifacts in GCS.

```mermaid
flowchart TB
    subgraph Sources["Sources"]
        direction LR
        Z[("Zoom")]
        DOC[("Docs")]
        SL[("Slack")]
    end

    subgraph Ingestion["Ingestion pipeline"]
        direction TB
        RAW["Raw files / uploads"]
        P1["1. Preprocess"]
        CF[["Cloud Function<br/>GCS file processor"]]
        P2["2. Pub/Sub dispatch"]
        PS[(Pub/Sub)]
        PROC["Processed folder<br/>(GCS)"]
        EVT["Object finalize /<br/>storage event"]
        ING[["RAG ingestor<br/>(Cloud Run)"]]
        CHUNK["Create chunks"]
        EMB["Embeddings"]
        VDB[("Vector store<br/>Vertex AI Vector Search")]

        RAW --> P1 --> CF --> P2 --> PS
        PS --> PROC --> EVT --> ING
        ING --> CHUNK --> EMB --> VDB
    end

    subgraph Answers["Answer generation pipeline"]
        direction TB
        ORCH[["RAG orchestrator<br/>(Cloud Function / Cloud Run)"]]
        INV["Invoke workers / agents"]
        RET["Retrieve — semantic search"]
        RERANK["Rerank chunks"]
        THR["Threshold / filter"]
        GEN["Answer generation (LLM)"]
        OUT["Response folder<br/>(GCS)"]

        ORCH --> INV --> RET --> RERANK --> THR --> GEN --> OUT
    end

    subgraph Guard["Rules & access"]
        RBAC["RBAC — who can read<br/>sources, chunks & responses"]
    end

    Z & DOC & SL --> RAW
    VDB -.->|queries| RET
    RBAC -.-> Sources
    RBAC -.-> Ingestion
    RBAC -.-> Answers
```

## How to view

- Paste the diagram into [Mermaid Live Editor](https://mermaid.live), or open this file in an editor / docs site that renders Mermaid (GitHub, many IDEs).
