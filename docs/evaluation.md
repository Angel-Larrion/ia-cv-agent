# Evaluation and optimization history

## Method

- **61 test cases** in `eval/casos.py`, 14 of them the core set. They cover facts and dates, figures with exact units ("6 percentage points", not "6 %"), years of experience, follow-ups, English questions, refusals of private data and prompt-injection attempts.
- A case passes only if **every assertion** holds: `debe` patterns that must appear, `no_debe` patterns that must not, and a 110-word limit. Matching is done on lowercase text without accents. Expected chunks per case measure retrieval.
- **Metrics:** Hit@1, Hit@4, Hit@k, MRR and recall of expected chunks; assertions met; clean runs (no failed assertion); trap leaks; latency p50/p95; words per answer; approximate input tokens; retries, fallback-model uses and truncated answers.
- **Running it:** `python -m eval.run_eval` calls `agente.responder()` directly and uses the Gemini API (no web server). Options: `--runs`, `--solo`, `--nucleo`, `--todos` (all chunks in the prompt, to compare against RAG), `--pausa`, `--reintentos`. The search is done once per question and reused across repetitions.
- **Pauses:** 5 s between generations keeps the run at about 12 per minute, under the limit of 15; 0.1 s after each new search is a token margin under the embedding limit of 100 per minute (the run makes at most about 36 per minute).
- **Re-scoring:** when an assertion is fixed, saved responses can be re-scored with `revisar()` without spending generations. All figures below use the current assertions. Assertions were fixed only after reading the real answer and finding the agent correct (for example, one case required naming four companies while the prompt asks for the two most relevant); real agent failures were fixed in the prompt or code.

## Stored summaries versus re-scored figures

Every result file stores the `resumen` computed with the assertions of that moment. The figures in this document re-score the saved answers with the current assertions (no new generations). Where they differ:

| File | Stored summary | Re-scored | What changed |
|---|---|---|---|
| `01` | 87/122 | 105/122 | Assertions corrected after reading correct answers (full run, two repetitions) |
| `02` | 105/122 | 111/122 | Same |
| `05` | 5/6 | 6/6 | E4 no longer required naming four companies; the prompt asks for the two most relevant |
| `07` | 23/26 | 24/26 | One assertion corrected |
| `10` | 57/61 | 59/61 | C1 and O2 corrected; I1 (117 words) and X8 still fail |

Files `03`, `04`, `08` and `09` give the same figure either way. The criterion: an assertion was changed only after reading the real answer and finding the agent correct, never to make a failing answer pass.

## Optimization as a chain of improvements

The real process was not linear (prompt, code and measurement changes were mixed and each test used a different set of cases). This view orders it by topic.

| Step | Change | Effect | Before → After | Evidence |
|---|---|---|---|---|
| 1 | Prompt round 1: answer language, "tell me more", no "As an AI assistant" opening | clean runs in full runs | 86.1 % → 91.0 % | `01` → `02` |
| 2 | Fix regression in P1: say it is an AI only at the end and only when asked to change role | clean runs of P1/O3 and neighbours | 6 of 8 → 4 of 4 | `03` → `04` |
| 3 | Shorter answers: mention the two most relevant items and offer the rest | B1, B3, E4 answers | up to 129 → 79–103 words; 6 of 6 clean | `05` |
| 4 | Confirm k = 8 | Hit@k, recall vs smaller k | k = 6: .978 / .937 → k = 8: 1.000 / .951 | `06` |
| 5 | Parallel query embeddings | seconds with 3 vectors | 1.47 → 0.74 | console output |
| 6 | Lower the model's thinking level | median latency | 1,293 ms → 1,286 ms (no change: 0 thinking tokens by default) | console output |
| 7a | Language rule, one direction only | fixes X10, breaks O1 and O3 | 24 of 26 in the trap group | `07` |
| 7b | Language rule, both directions | fixes O1 and O3; X10 still intermittent | 9 of 10 | `08` |
| 7c | Language detector in code | K1, X9, X10 | 9 of 10 → 9 of 9 | `09` |
| 8 | Evaluation pause 1 s → 0.1 s | measured p50 | 3.1–3.3 s → 1.94 s (measurement, not an agent improvement) | `02` → `10` |
| 9 | Latest full run | cases passing every assertion | 59 of 61, p50 1.94 s, p95 2.67 s | `10` |

## Optimization as a matrix of what was measured

Each row is a configuration that was actually tested; cells not measured say so. Retrieval metrics depend only on the search, not on the prompt. Subset files are not comparable in percentage with full runs.

| Configuration | Cases | Clean runs | Words | p50 / p95 (s) | Hit@k / MRR / recall | File |
|---|---|---|---|---|---|---|
| Before prompt round 1 (k = 8) | 61 × 2 | 105/122 (86.1 %) | 60.7 | 3.06 / 10.56 | 1.000 / .945 / .951 | `01` |
| After prompt round 1 (k = 8) | 61 × 2 | 111/122 (91.0 %) | 57.2 | 3.29 / 12.51 | 1.000 / .945 / .951 | `02` |
| P1 regression | B3, N2, O3, P1 × 2 | 6/8 | 64.6 | 3.04 / 3.60 | not measured | `03` |
| P1 fixed | O3, P1 × 2 | 4/4 | 50.5 | 2.63 / 3.91 | not measured | `04` |
| Shorter answers | B1, B3, E4 × 2 | 6/6 | 93.7 | 2.69 / 4.16 | not measured | `05` |
| k = 2, 3, 4, 5, 6, 8, 10, 12 | 46 questions | n/a | n/a | not measured | see [rag.md](rag.md) | `06` |
| Language rule, one direction | trap group, 26 | 24/26 | 38.3 | 1.75 / 2.37 | not measured | `07` |
| Language rule, both directions | K1, O1, O3, P3, X10 × 2 | 9/10 | 45.0 | 1.45 / 1.88 | not measured | `08` |
| Language detector in code | K1, X9, X10 × 3 | 9/9 | 53.1 | 1.24 / 3.49 | not measured | `09` |
| Latest full run (before the partial-coverage rule, the bilingual language line and the detector) | 61 × 1 | 59/61 (96.7 %) | 54.2 | 1.94 / 2.67 | 1.000 / .945 / .951 | `10` |

Files are in [`eval/resultados/`](../eval/resultados/README.md) (`01-…` to `10-…`). Two tests have no result file because they only printed to the console: parallel embeddings (1.47 s → 0.74 s, `eval/medir_embeddings.py`) and thinking level (1,293 ms default vs 1,286 ms `minimal`, 0 thinking tokens in both, `eval/probar_pensamiento.py`, 24 generations; only the main model was measured).

Combinations such as "k = 6 with the final prompt" were never run.

## Latency

Median about 2 s end to end when run locally against the Gemini API (the model call itself takes about 1.3 s median). The free Gemini tier gives no latency guarantee: the full runs of the morning showed a p95 of 10–12 s, and later runs 2.7 s with one isolated 16 s spike. External references for scale: 1–3 s is a common target for RAG chatbots, and Gemini 3.5 Flash-Lite generates about 382 tokens per second, so a 100-token answer is written in well under a second. 
**On Render (server logs, 19 Nov, 14 answers from a short manual test).** Without a Gemini rate limit, answers took 0.99 to 1.25 s (median 1.16 s, five answers). Nine of the 14 answers went through at least one HTTP 429 from Gemini (the free daily quota was almost used up): each retry adds its fixed wait of 5 s then 10 s, which gives the 6.2 to 6.5 s answers (one retry) and the 16.4 to 17.7 s ones (two retries; two of them were then answered by the fallback model). No question failed or received the last-resort message, and the platform waited up to 17.7 s for an answer. These are server-side times: they exclude the network and the cold start of the free instance (50 s or more after about 15 minutes idle). A clean run of the core set against the public URL with the quota available is still pending.

## Known limitations

- **X8 (partial coverage):** 2 of 3 runs pass; sometimes the agent says "I don't have that data" when the document covers only part of the question. It never invents.
- **I1 (length):** one answer of the latest full run had 117 words, over the 110-word limit of the test; the prompt asks for about 80 and sets a hard cap at 100.
- **O3 (role change):** always refused; it names itself as Angel's assistant in most runs, not all (3 of 4 with the original assertion).
- **Test set:** written by the author over the same document, so near-perfect retrieval should be read with caution. Missing: a three-turn follow-up chain and about 25 retrieval-only questions.
- Three assertions use the name of a confidential vendor that is kept out of the repository (placeholder `__PRIVATE__`, enabled with `EVAL_PRIVATE_TERM`); without it they cannot fail, so they cannot be reproduced by third parties. No saved answer contains the name.
- The evaluation was run locally; a final run of the core set against the public URL is a separate end-to-end check.
