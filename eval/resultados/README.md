# Evaluation results kept as evidence

Each file is the raw JSON saved by `python -m eval.run_eval` (or `eval.comparar_k`). All figures below were **re-scored with the current assertions** in `eval/casos.py`, so the raw `resumen` inside an older file (scored with the assertions of that moment) can show a lower number. The final full run is from 20 Nov (file 11); the one before it is from 19 Nov at 13:47 (file 10). Where the stored `resumen` and the re-scored figure differ (files 01, 02, 05, 07 and 10), both are listed in [docs/evaluation.md](../../docs/evaluation.md#stored-summaries-versus-re-scored-figures); for example file 10 stores 57/61 and re-scores to 59/61. In files 01, 02, 05, 07 and 10 the name of a confidential vendor was replaced by the placeholder `__PRIVATE__` inside the stored assertion patterns; no saved answer contains it (368 answers checked), so no score changes. Subset files cover only the cases listed in the name, so their percentages are not comparable with the full runs.

Ranking, recall and latency columns come from the same files. "n/m" means not measured. Retrieval columns do not change with the prompt because the search was not touched.

| Change tested | State | Cases | Clean runs | Words (mean) | p50 / p95 (s) | Hit@k / MRR / recall | File |
|---|---|---|---|---|---|---|---|
| Prompt round 1 (language, "cuéntame más", opening) | before | 61 x 2 | 105/122 (86.1 %) | 60.7 | 3.06 / 10.56 | 1.000 / .945 / .951 | `01-prompt-ronda1-ANTES-corrida-completa.json` |
| | after | 61 x 2 | 111/122 (91.0 %) | 57.2 | 3.29 / 12.51 | 1.000 / .945 / .951 | `02-prompt-ronda1-DESPUES-corrida-completa.json` |
| Fix P1 regression ("Como asistente de IA...") | before | B3, N2, O3, P1 x 2 | 6/8 | 64.6 | 3.04 / 3.60 | n/m | `03-regresion-P1-ANTES.json` |
| | after | O3, P1 x 2 | 4/4 | 50.5 | 2.63 / 3.91 | n/m | `04-regresion-P1-DESPUES.json` |
| Shorter answers (B1, B3, E4) | after | B1, B3, E4 x 2 | 6/6 | 93.7 | 2.69 / 4.16 | n/m | `05-respuestas-largas-B1-B3-E4-DESPUES.json` |
| Value of k (2 to 12), embeddings only | k=2, 3, 4, 5, 6, 8, 10, 12 | 46 questions | n/a | n/a | n/m | see file (k=8: 1.000 / .945 / .951) | `06-comparar-k-2-a-12.json` |
| Language rule in the prompt, one direction only | regression | trap group, 26 runs | 24/26 | 38.3 | 1.75 / 2.37 | n/m | `07-idioma-regresion-grupo-trampas-ANTES.json` |
| Language rule in the prompt, both directions | after | K1, O1, O3, P3, X10 x 2 | 9/10 | 45.0 | 1.45 / 1.88 | n/m | `08-idioma-prompt-bilingue-X10-intermitente.json` |
| Language detector in code | after | K1, X9, X10 x 3 | 9/9 | 53.1 | 1.24 / 3.49 | n/m | `09-idioma-detector-K1-X9-X10-DESPUES.json` |
| Full verification at 13:47 on 19 Nov (before the X8 prompt rule, the bilingual language line and the language detector; pause 0.1 s) | previous full run | 61 x 1 | 59/61 (96.7 %) | 54.2 | 1.94 / 2.67 | 1.000 / .945 / .951 | `10-verificacion-1347-previa-al-detector.json` |
| Final full run, 20 Nov, current code (Gemini slow that day: 503 errors, 4 retries) | latest full run | 61 x 1 | 57/61 (93.4 %) | 49.3 | 3.70 / 17.51 | 1.000 / .945 / .951 | `11-corrida-completa-final-20nov.json` |
| Repetition of the four failed cases (C2, E2, J2, P3), no retries | after | C2, E2, J2, P3 x 3 | 9/12 (C2, E2, J2 3/3; P3 0/3) | 70.4 | 2.22 / 6.72 | n/m (4 cases only) | `12-repeticion-C2-E2-J2-P3-20nov.json` |
| Retrieval turned off (`--todos`: all of `proyectos.md` in the prompt) | compared with `11` | 61 x 1 | 59/61 (96.7 %) | 51.9 | 3.70 / 14.70 | n/m (no retrieval) | `13-todos-contexto-completo-20nov.json` |

Tested without a result file (console output only, figures in `docs/rag.md`): parallel embeddings (3 sequential vectors 1.47 s, parallel 0.74 s) and model thinking level (default 1,293 ms, `minimal` 1,286 ms, 0 thinking tokens in both).
