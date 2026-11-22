# AuditGym check report

- env_version: `1.0.0`, python 3.13.18, Linux-6.18.44-fc-v726-x86_64-with-glibc2.39
- overall: **PASSED** (7.3s)

| check | result |
|---|---|
| unit tests | 56 run, 0 failures, 0 errors |
| reproducibility (train+dev regenerate == committed) | True |
| data verification (40 episodes) | 0 failures |
| paired checks | 20/20 |
| leak scan | True |

## Baselines on dev (eval mode, policies in separate processes)

| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 17.2 | 0.0072 | {'duplicate_invoice': 8, 'fx_misconversion': 3, 'period_cutoff': 4, 'unallocated_payment': 3} | {'duplicate_invoice': 8, 'fx_misconversion': 13, 'period_cutoff': 10, 'unallocated_payment': 10} |
| reconciler | 0.415 | 0.669 | 0.498 | -0.030 | -1.0 | 0.2128 | 17.0 | 0.0115 | {'duplicate_invoice': 18, 'fx_misconversion': 23, 'period_cutoff': 10} | {'fx_misconversion': 7} |
| flag_all | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 3.9 | 0.0056 | {'duplicate_invoice': 80, 'fx_misconversion': 80, 'period_cutoff': 70, 'unallocated_payment': 70} | {'duplicate_invoice': 8, 'fx_misconversion': 13, 'period_cutoff': 10, 'unallocated_payment': 10} |
| oracle | 0.800 | 0.800 | 1.000 | +1.000 | 1.0 | 1.0 | 1.0 | 0.0002 | - | - |
| expert | 0.800 | 0.800 | 1.000 | +0.968 | 0.973 | 0.9667 | 17.0 | 0.0123 | - | - |

## Baselines on local_holdout (eval mode, policies in separate processes)

| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.000 | 0.000 | 0.050 | -0.900 | -0.602 | -1.0 | 18.1 | 0.0070 | {'duplicate_invoice': 9, 'fx_misconversion': 10, 'period_cutoff': 6, 'unallocated_payment': 2} | {'duplicate_invoice': 15, 'fx_misconversion': 24, 'period_cutoff': 16, 'unallocated_payment': 18} |
| reconciler | 0.342 | 0.556 | 0.411 | -0.206 | -1.0 | 0.0589 | 18.8 | 0.0119 | {'duplicate_invoice': 41, 'fx_misconversion': 40, 'period_cutoff': 24} | {'fx_misconversion': 14, 'period_cutoff': 6} |
| flag_all | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 4.0 | 0.0039 | {'duplicate_invoice': 160, 'fx_misconversion': 160, 'period_cutoff': 140, 'unallocated_payment': 140} | {'duplicate_invoice': 15, 'fx_misconversion': 24, 'period_cutoff': 16, 'unallocated_payment': 18} |
| oracle | 0.750 | 0.750 | 1.000 | +1.000 | 1.0 | 1.0 | 1.0 | 0.0002 | - | - |
| expert | 0.750 | 0.750 | 1.000 | +0.965 | 0.9684 | 0.9632 | 18.8 | 0.0078 | - | - |

Precision/recall are 0 by definition when their denominator is 0 (e.g. clean books answered with no findings), so mean P/R are below 1 even for the oracle; F1 and return follow the spec (empty truth + empty answer => F1 = 1).

