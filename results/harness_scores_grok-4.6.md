# Harness aggregate scores (bootstrap 95% CI) — grok-4.6

Each cell: `mean [ci_low, ci_high]`. Point estimate = mean(per_sample); CI via bootstrap.
params: n_boot=10000, alpha=0.05, seed=12345.
Sorted by `mean_progress_rate` mean (descending) within each condition.

## baseline

| rank | harness | mean_progress_rate | max_progress_rate | mean_memory_progress_rate | max_memory_progress_rate | mean_overall_progress_rate | max_overall_progress_rate | token_efficiency | turn_efficiency | llm_call_efficiency | total_tokens | total_latency_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | grok-build | 0.5897 [0.5008, 0.6743] | 0.6638 [0.5718, 0.7543] | - | - | - | - | 0.4530 [0.2713, 0.6876] | 0.0731 [0.0591, 0.0882] | 0.0097 [0.0075, 0.0125] | 2,898,785 [2,010,218, 3,898,834] | 403,625 [321,420, 489,897] |

## scenario_1_normal

| rank | harness | mean_progress_rate | max_progress_rate | mean_memory_progress_rate | max_memory_progress_rate | mean_overall_progress_rate | max_overall_progress_rate | token_efficiency | turn_efficiency | llm_call_efficiency | total_tokens | total_latency_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | grok-build | 0.6238 [0.5507, 0.6992] | 0.6918 [0.6137, 0.7687] | 0.8651 [0.8242, 0.9034] | 0.9094 [0.8692, 0.9441] | - | - | 0.2261 [0.1352, 0.3400] | 0.0562 [0.0471, 0.0659] | 0.0087 [0.0071, 0.0106] | 6,265,968 [4,406,167, 8,308,449] | 6,100,246 [4,985,488, 7,303,952] |

## scenario_2_contradict

| rank | harness | mean_progress_rate | max_progress_rate | mean_memory_progress_rate | max_memory_progress_rate | mean_overall_progress_rate | max_overall_progress_rate | token_efficiency | turn_efficiency | llm_call_efficiency | total_tokens | total_latency_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | grok-build | 0.6203 [0.5269, 0.7120] | 0.6978 [0.6068, 0.7870] | 0.6615 [0.5935, 0.7211] | 0.6690 [0.6047, 0.7298] | - | - | 0.2504 [0.1484, 0.3838] | 0.0739 [0.0592, 0.0899] | 0.0100 [0.0078, 0.0127] | 4,958,024 [3,547,958, 6,514,391] | 2,336,321 [1,521,265, 3,300,192] |

## scenario_3_policy

| rank | harness | mean_progress_rate | max_progress_rate | mean_memory_progress_rate | max_memory_progress_rate | mean_overall_progress_rate | max_overall_progress_rate | token_efficiency | turn_efficiency | llm_call_efficiency | total_tokens | total_latency_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | grok-build | 0.6146 [0.5347, 0.6912] | 0.7062 [0.6182, 0.7907] | 0.5734 [0.4601, 0.6899] | 0.6679 [0.5516, 0.7803] | - | - | 0.2064 [0.1390, 0.2902] | 0.0783 [0.0581, 0.1044] | 0.0094 [0.0076, 0.0114] | 5,565,487 [3,945,638, 7,388,153] | 1,371,858 [1,084,544, 1,662,174] |
