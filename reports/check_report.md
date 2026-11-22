# AuditGym check report

- env_version: `1.0.0`, python 3.11.18, Linux-6.18.44-fc-v726-x86_64-with-glibc2.39
- overall: **PASSED** (10.6s)

| check | result |
|---|---|
| unit tests | 64 run, 0 failures, 0 errors |
| reproducibility (train+dev regenerate == committed) | True |
| data verification (40 episodes) | 0 failures |
| paired checks | 20/20 |
| leak scan | True |

## Baselines on dev (eval mode, policies in separate processes)

| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.000 | 0.000 | 0.100 | -0.805 | -0.026 | -1.0 | 17.5 | 0.0065 | {'duplicate_invoice': 3, 'fx_misconversion': 4, 'period_cutoff': 4, 'unallocated_payment': 3} | {'duplicate_invoice': 8, 'fx_misconversion': 12, 'period_cutoff': 9, 'unallocated_payment': 8} |
| reconciler | 0.217 | 0.584 | 0.310 | -0.409 | -1.0 | -0.2616 | 18.9 | 0.0090 | {'duplicate_invoice': 19, 'fx_misconversion': 44, 'period_cutoff': 16} | {'fx_misconversion': 9, 'period_cutoff': 1} |
| flag_all | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 4.5 | 0.0058 | {'duplicate_invoice': 80, 'fx_misconversion': 80, 'period_cutoff': 70, 'unallocated_payment': 70} | {'duplicate_invoice': 8, 'fx_misconversion': 12, 'period_cutoff': 9, 'unallocated_payment': 8} |
| oracle | 0.800 | 0.800 | 1.000 | +1.000 | 1.0 | 1.0 | 1.0 | 0.0003 | - | - |
| expert | 0.800 | 0.800 | 1.000 | +0.964 | 0.969 | 0.963 | 18.9 | 0.0096 | - | - |

## Baselines on local_holdout (eval mode, policies in separate processes)

| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.000 | 0.000 | 0.100 | -0.805 | -0.2184 | -1.0 | 16.1 | 0.0051 | {'duplicate_invoice': 5, 'fx_misconversion': 6, 'period_cutoff': 4, 'unallocated_payment': 9} | {'duplicate_invoice': 11, 'fx_misconversion': 27, 'period_cutoff': 20, 'unallocated_payment': 18} |
| reconciler | 0.358 | 0.682 | 0.451 | -0.123 | -1.0 | 0.1695 | 16.7 | 0.0085 | {'duplicate_invoice': 37, 'fx_misconversion': 42, 'period_cutoff': 22} | {'fx_misconversion': 8} |
| flag_all | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 3.9 | 0.0053 | {'duplicate_invoice': 144, 'fx_misconversion': 144, 'period_cutoff': 126, 'unallocated_payment': 126} | {'duplicate_invoice': 11, 'fx_misconversion': 24, 'period_cutoff': 19, 'unallocated_payment': 17} |
| oracle | 0.750 | 0.750 | 1.000 | +1.000 | 1.0 | 1.0 | 1.0 | 0.0003 | - | - |
| expert | 0.750 | 0.750 | 1.000 | +0.969 | 0.9728 | 0.9672 | 16.7 | 0.0084 | - | - |

Precision/recall are 0 by definition when their denominator is 0 (e.g. clean books answered with no findings), so mean P/R are below 1 even for the oracle; F1 and return follow the spec (empty truth + empty answer => F1 = 1).

