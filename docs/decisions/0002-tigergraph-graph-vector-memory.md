# ADR-0002: TigerGraph as graph and vector memory

**Status:** Accepted — 22 September 2026

## Context

The challenge requires TigerGraph for graph/vector storage and GraphRAG. Investigations need exact structural connections and narrative/policy similarity.

## Decision

Store entities, relationships, cases, evidence, actions, policy/document chunks, and embeddings in TigerGraph. Retrieve prior cases through structural candidates plus vector similarity, fused with provenance and time filters.

## Consequences

The system demonstrates TigerGraph throughout the product, avoids a second database on the critical path, and can trace semantic results back to graph entities. Schema and loading design must account for both operational queries and vector chunks.
