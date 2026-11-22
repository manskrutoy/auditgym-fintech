# AuditGym check report

- env_version: `1.0.0`, python 3.11.18, Linux-6.18.44-fc-v726-x86_64-with-glibc2.39
- overall: **PASSED** (10.6s)

| check | result |
|---|---|
| unit tests | 78 run, 0 failures, 0 errors |
| reproducibility (train+dev regenerate == committed) | True |
| data verification (40 episodes) | 0 failures |
| paired checks | 20/20 |
| leak scan | True |

## Baselines on dev (eval mode, policies in separate processes)

| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.000 | 0.000 | 0.100 | -0.805 | -0.026 | -1.0 | 19.8 | 0.0082 | {'duplicate_invoice': 3, 'fx_misconversion': 3, 'period_cutoff': 5, 'unallocated_payment': 3} | {'duplicate_invoice': 8, 'fx_misconversion': 11, 'period_cutoff': 9, 'unallocated_payment': 8} |
| reconciler | 0.258 | 0.581 | 0.344 | -0.340 | -1.0 | -0.1746 | 18.4 | 0.0112 | {'duplicate_invoice': 17, 'fx_misconversion': 33, 'period_cutoff': 16} | {'fx_misconversion': 9, 'period_cutoff': 1} |
| flag_all | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 4.3 | 0.0067 | {'duplicate_invoice': 80, 'fx_misconversion': 80, 'period_cutoff': 70, 'unallocated_payment': 70} | {'duplicate_invoice': 8, 'fx_misconversion': 11, 'period_cutoff': 9, 'unallocated_payment': 8} |
| oracle | 0.800 | 0.800 | 1.000 | +1.000 | 1.0 | 1.0 | 1.0 | 0.0007 | - | - |
| expert | 0.800 | 0.800 | 1.000 | +0.965 | 0.969 | 0.9643 | 18.4 | 0.0105 | - | - |

## Baselines on local_holdout (eval mode, policies in separate processes)

| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.000 | 0.000 | 0.100 | -0.805 | -0.2184 | -1.0 | 16.4 | 0.0050 | {'duplicate_invoice': 6, 'fx_misconversion': 6, 'period_cutoff': 4, 'unallocated_payment': 9} | {'duplicate_invoice': 10, 'fx_misconversion': 25, 'period_cutoff': 21, 'unallocated_payment': 17} |
| reconciler | 0.377 | 0.674 | 0.462 | -0.101 | -1.0 | 0.1984 | 16.7 | 0.0120 | {'duplicate_invoice': 36, 'fx_misconversion': 37, 'period_cutoff': 19} | {'fx_misconversion': 8, 'period_cutoff': 1} |
| flag_all | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 4.0 | 0.0049 | {'duplicate_invoice': 160, 'fx_misconversion': 160, 'period_cutoff': 140, 'unallocated_payment': 140} | {'duplicate_invoice': 10, 'fx_misconversion': 25, 'period_cutoff': 21, 'unallocated_payment': 17} |
| oracle | 0.750 | 0.750 | 1.000 | +1.000 | 1.0 | 1.0 | 1.0 | 0.0003 | - | - |
| expert | 0.750 | 0.750 | 1.000 | +0.969 | 0.9728 | 0.9672 | 16.7 | 0.0091 | - | - |

Precision/recall are 0 by definition when their denominator is 0 (e.g. clean books answered with no findings), so mean P/R are below 1 even for the oracle; F1 and return follow the spec (empty truth + empty answer => F1 = 1).

