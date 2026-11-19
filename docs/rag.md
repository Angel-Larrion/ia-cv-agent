# How the retrieval was built

This page explains each choice in the retrieval layer (`rag.py`, `scripts/build_index.py`, `data/`). Numbers come from `eval/` and are kept in [eval/resultados/](../eval/resultados/README.md).

## Role of RAG

The whole project document would fit in one prompt (roughly 9,000 to 10,000 tokens, estimated from the 36 KB file size, not counted with the model's tokenizer). RAG is used as a precision layer: it sends fewer tokens, keeps the model focused and scales if the document grows, and it is measurable with Hit@k and MRR. Because it is only a layer, any retrieval failure falls back to sending all chunks, so the agent still answers.

## What is indexed and what is not

- `data/cv.md` goes **whole** in every prompt and is never indexed. It is short and holds what must not depend on a search: identity, dates, titles, education and contact.
- `data/proyectos.md` is the only indexed file: **51 chunks**, one per `###` heading. A single knowledge document with clear headings avoids keeping several files and an index that drifts out of sync.

## Chunking

- One chunk per heading, titled `Company and stage (period) · Topic (English keywords)`. `#`/`##` headings and `---` rules close a chunk without starting another, so the last chunk of a section does not carry the next section's title.
- Chunks follow meaning, not a fixed size; the title carries company and period (it helps retrieval and the company boost), and the English keywords help English questions and acronyms (IFRS 9, CNBV, DBT, PD/LGD).
- **No overlap:** cuts fall on hand-written headings, so each idea is already whole and each chunk is understandable alone. Overlap solves a problem of fixed-size cutting that does not exist here.
- Measured: 51 chunks, 266 to 1,098 characters (median 569). `build_index.py` asserts the count, so a broken heading fails loudly.

## Embeddings and index

- Model `gemini-embedding-001`, task types `RETRIEVAL_DOCUMENT` for chunks and `RETRIEVAL_QUERY` for questions, the same `embeber()` function and constants for both. The model is read from `EMBED_MODEL` and stored in the index.
- **768 dimensions.** The model produces 3072 and was trained so that shortening to 768 loses little; for 51 chunks the size difference is irrelevant, and 768 keeps `index.json` small (about 435 KB). Retrieval was good enough (Hit@k = 1.0) that other sizes were not tried.
- Vectors are normalized to unit length (required below 3072 dimensions), so cosine similarity is a dot product. Stored values are rounded to six decimals and re-normalized on load.
- The index is **precomputed** and committed: it saves quota (embeddings allow 1,000 per day on the free tier), removes startup latency and is reproducible. Live, only the question is embedded.
- The index stores model, dimensions, date and a **content hash** computed over chunk titles and text (not file bytes, so Windows and Linux line endings give the same hash). On load, a mismatch with the current `proyectos.md` raises a clear error and the agent uses the full-context fallback.
- "Index" here means a table of precomputed vectors, not an approximate-search structure.

## Search

- **Exact cosine similarity with NumPy**, no IVF, HNSW, FAISS or vector database: with 51 vectors of 768 numbers the comparison takes a fraction of a millisecond, is always exact and adds nothing to maintain.
- **No relevance threshold:** similarities between chunks of the same document are high (median 0.80, min 0.64, max 0.95), so an absolute cut-off hardly separates relevant from irrelevant. Off-topic questions are handled by the prompt rules instead.
- **Company boost:** chunks whose title company (Propaga, Stori, Coppel, SAS) is named in the question get +0.03, using word boundaries so "SAS" does not match "casas". The value was not tuned because Hit@k is already 1.0.
- **Follow-ups:** the platform resends the whole history and the agent keeps no session. A question like "and what was the result?" or "tell me more" alone matches nothing, so up to three query vectors are used and each chunk keeps its best score:
  1. the question alone (protects topic changes);
  2. previous user message + question;
  3. two previous user messages + question (covers chains where the previous message no longer names the topic).
  Only user messages are embedded: they are the cleanest topic signal, and a long agent answer would dominate the vector. The first turn uses one vector, the second two, from the third on three. The vectors are requested **in parallel**.

### Choosing k

`eval/comparar_k.py`, 46 questions with expected chunks, embeddings only (no generations):

| k | Hit@k | MRR | Recall | Fragment tokens (mean) |
|---|---|---|---|---|
| 2 | .957 | .935 | .781 | 309 |
| 3 | .978 | .942 | .833 | 452 |
| 4 | .978 | .942 | .846 | 595 |
| 5 | .978 | .942 | .895 | 749 |
| 6 | .978 | .942 | .937 | 903 |
| **8** | **1.000** | .945 | **.951** | 1,196 |
| 10 | 1.000 | .945 | .957 | 1,488 |
| 12 | 1.000 | .945 | .964 | 1,798 |

k = 8 is the smallest value where no question loses its expected chunk. Going to 6 saves about 293 tokens (8 % of the prompt) but loses question A2 and 1.4 points of recall; going to 10 adds 292 tokens for 0.6 points of recall and changes neither Hit@k nor MRR. Latency per k was not measured (an external study reports about +0.4 s from k = 3 to k = 7). k = 7 and 9 were not tried.

### Parallel query embeddings

`eval/medir_embeddings.py` (five alternating repetitions, no generation): three vectors one after another, median 1.47 s; in parallel, 0.74 s. It saves 0.73 s with three vectors and about 0.37 s with two; the first turn is unchanged.

## When something fails

Retrieval errors (quota, network, stale index) never fail the request: all chunks go into the prompt and the model answers anyway. The order is: retry on the main model → fallback model → all chunks in the prompt → friendly message with a profile summary built from `cv.md`. Generation shares a 40 s budget (20 s per call, no new attempt under 3 s left).

## Not done, on purpose

- Reranking or query rewriting with an LLM: each costs one more generation per question from a 500-per-day quota and adds latency, with Hit@k already 1.0.
- Keyword search (BM25) fused with embeddings: no retrieval problem to fix; it would add accent and stop-word handling and one more parameter.
- Approximate nearest-neighbor indexes and vector databases: see above.
- A relevance threshold: see above.
