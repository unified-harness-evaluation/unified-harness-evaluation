# Behavior analysis — high-level overview

Matrix: 4 harnesses × 4 scenarios × up to 10 samples. Tag counts are codebook groups summed over each cell's annotated traces.

### Codebook group counts — scenario: baseline

| harness | files | total | Retrieval | Memory | Planning | Reasoning | Evaluate | Deciding | Grounding | Executing | Learning | Reflection |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grok-build | 10 | 252 | 44 | 20 | 19 | 70 | 27 | 14 | 24 | 19 | 0 | 15 |
| goose | 10 | 260 | 20 | 7 | 28 | 66 | 36 | 5 | 55 | 23 | 1 | 19 |
| mistral-vibe | 10 | 212 | 4 | 22 | 5 | 80 | 45 | 15 | 18 | 7 | 0 | 16 |
| kilocode | 10 | 253 | 24 | 17 | 17 | 67 | 52 | 2 | 34 | 31 | 0 | 9 |

### Codebook group counts — scenario: normal

| harness | files | total | Retrieval | Memory | Planning | Reasoning | Evaluate | Deciding | Grounding | Executing | Learning | Reflection |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grok-build | 10 | 261 | 16 | 66 | 11 | 90 | 31 | 2 | 17 | 13 | 0 | 15 |
| goose | 10 | 276 | 22 | 45 | 23 | 73 | 35 | 7 | 41 | 17 | 0 | 13 |
| mistral-vibe | 10 | 277 | 20 | 87 | 3 | 86 | 39 | 2 | 11 | 24 | 0 | 5 |
| kilocode | 10 | 307 | 42 | 76 | 5 | 66 | 35 | 30 | 11 | 22 | 0 | 20 |

### Codebook group counts — scenario: contradict

| harness | files | total | Retrieval | Memory | Planning | Reasoning | Evaluate | Deciding | Grounding | Executing | Learning | Reflection |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grok-build | 10 | 287 | 28 | 24 | 21 | 56 | 50 | 28 | 25 | 21 | 0 | 34 |
| goose | 10 | 242 | 29 | 27 | 21 | 43 | 43 | 18 | 24 | 17 | 0 | 20 |
| mistral-vibe | 10 | 245 | 3 | 23 | 1 | 58 | 48 | 26 | 43 | 28 | 0 | 15 |
| kilocode | 10 | 238 | 30 | 10 | 4 | 49 | 46 | 25 | 31 | 37 | 0 | 6 |

### Codebook group counts — scenario: policy

| harness | files | total | Retrieval | Memory | Planning | Reasoning | Evaluate | Deciding | Grounding | Executing | Learning | Reflection |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grok-build | 10 | 289 | 21 | 33 | 27 | 71 | 79 | 20 | 13 | 15 | 0 | 10 |
| goose | 10 | 295 | 15 | 31 | 32 | 70 | 54 | 18 | 47 | 20 | 0 | 8 |
| mistral-vibe | 10 | 306 | 5 | 43 | 1 | 64 | 79 | 21 | 84 | 1 | 0 | 8 |
| kilocode | 10 | 364 | 30 | 35 | 4 | 68 | 93 | 32 | 53 | 27 | 0 | 22 |

### Component kinds — scenario: baseline

| harness | retrieval | mutate | compute | other |
|---|---|---|---|---|
| grok-build | 249 | 147 | 151 | 45 |
| goose | 181 | 154 | 183 | 33 |
| mistral-vibe | 226 | 105 | 152 | 95 |
| kilocode | 157 | 116 | 113 | 169 |

### Component kinds — scenario: normal

| harness | retrieval | mutate | compute | other |
|---|---|---|---|---|
| grok-build | 271 | 199 | 161 | 37 |
| goose | 109 | 178 | 194 | 26 |
| mistral-vibe | 271 | 160 | 205 | 103 |
| kilocode | 205 | 161 | 140 | 184 |

### Component kinds — scenario: contradict

| harness | retrieval | mutate | compute | other |
|---|---|---|---|---|
| grok-build | 250 | 190 | 183 | 49 |
| goose | 154 | 188 | 209 | 31 |
| mistral-vibe | 256 | 152 | 167 | 120 |
| kilocode | 154 | 118 | 181 | 182 |

### Component kinds — scenario: policy

| harness | retrieval | mutate | compute | other |
|---|---|---|---|---|
| grok-build | 268 | 185 | 166 | 79 |
| goose | 166 | 168 | 147 | 21 |
| mistral-vibe | 301 | 179 | 222 | 171 |
| kilocode | 179 | 133 | 188 | 133 |

### Trap-level recall (denominator = injected traps, constant across harnesses)

| harness | scenario | pure_recall | recall+action | re_retrieved | not_surfaced | traps | recall_rate |
|---|---|---|---|---|---|---|---|
| grok-build | normal | 7 | 19 | 37 | 2 | 65 | 40% |
| grok-build | contradict | 5 | 4 | 9 | 8 | 26 | 35% |
| grok-build | policy | 4 | 10 | 15 | 1 | 30 | 47% |
| goose | normal | 6 | 38 | 15 | 6 | 65 | 68% |
| goose | contradict | 3 | 12 | 3 | 8 | 26 | 58% |
| goose | policy | 4 | 12 | 13 | 1 | 30 | 53% |
| mistral-vibe | normal | 16 | 17 | 30 | 2 | 65 | 51% |
| mistral-vibe | contradict | 2 | 4 | 12 | 8 | 26 | 23% |
| mistral-vibe | policy | 3 | 10 | 16 | 1 | 30 | 43% |
| kilocode | normal | 7 | 25 | 30 | 3 | 65 | 49% |
| kilocode | contradict | 2 | 10 | 6 | 8 | 26 | 46% |
| kilocode | policy | 11 | 6 | 13 | 0 | 30 | 57% |

### Memory-query credited rate

| harness | scenario | credited | total | rate |
|---|---|---|---|---|
| grok-build | normal | 161 | 179 | 0.9 |
| grok-build | contradict | 70 | 99 | 0.71 |
| grok-build | policy | 52 | 94 | 0.55 |
| goose | normal | 134 | 179 | 0.75 |
| goose | contradict | 70 | 99 | 0.71 |
| goose | policy | 46 | 94 | 0.49 |
| mistral-vibe | normal | 152 | 179 | 0.85 |
| mistral-vibe | contradict | 71 | 99 | 0.72 |
| mistral-vibe | policy | 55 | 94 | 0.59 |
| kilocode | normal | 153 | 179 | 0.85 |
| kilocode | contradict | 63 | 99 | 0.64 |
| kilocode | policy | 59 | 94 | 0.63 |
