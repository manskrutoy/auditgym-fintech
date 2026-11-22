# AuditGym check report

- env_version: `1.0.0`, python 3.13.18, Linux-6.18.44-fc-v726-x86_64-with-glibc2.39
- overall: **PASSED** (6.7s)

| check | result |
|---|---|
| unit tests | 53 run, 0 failures, 0 errors |
| reproducibility (train+dev regenerate == committed) | True |
| data verification (40 episodes) | 0 failures |
| paired checks | 20/20 |
| leak scan | True |

## Baselines on dev (eval mode, policies in separate processes)

| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.000 | 0.000 | 0.100 | -0.806 | -0.03 | -1.0 | 24.2 | 0.0090 | {'duplicate_invoice': 3, 'fx_misconversion': 4, 'period_cutoff': 3, 'unallocated_payment': 3} | {'duplicate_invoice': 7, 'fx_misconversion': 13, 'period_cutoff': 9, 'unallocated_payment': 9} |
| reconciler | 0.372 | 0.571 | 0.446 | -0.130 | -1.0 | 0.0872 | 15.8 | 0.0097 | {'duplicate_invoice': 20, 'fx_misconversion': 9, 'period_cutoff': 11} | {'fx_misconversion': 5, 'period_cutoff': 3} |
| flag_all | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 3.9 | 0.0057 | {'duplicate_invoice': 80, 'fx_misconversion': 80, 'period_cutoff': 70, 'unallocated_payment': 70} | {'duplicate_invoice': 7, 'fx_misconversion': 13, 'period_cutoff': 9, 'unallocated_payment': 9} |
| oracle | 0.800 | 0.800 | 1.000 | +1.000 | 1.0 | 1.0 | 1.0 | 0.0002 | - | - |
| expert | 0.800 | 0.800 | 1.000 | +0.970 | 0.975 | 0.9692 | 15.8 | 0.0085 | - | - |

## Baselines on local_holdout (eval mode, policies in separate processes)

| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.000 | 0.000 | 0.050 | -0.901 | -0.6028 | -1.0 | 15.7 | 0.0046 | {'duplicate_invoice': 6, 'fx_misconversion': 8, 'period_cutoff': 14, 'unallocated_payment': 7} | {'duplicate_invoice': 14, 'fx_misconversion': 21, 'period_cutoff': 17, 'unallocated_payment': 18} |
| reconciler | 0.342 | 0.637 | 0.418 | -0.189 | -1.0 | 0.0818 | 17.0 | 0.0075 | {'duplicate_invoice': 44, 'fx_misconversion': 32, 'period_cutoff': 16} | {'fx_misconversion': 10, 'period_cutoff': 4} |
| flag_all | 0.000 | 0.000 | 0.000 | -1.000 | -1.0 | -1.0 | 4.1 | 0.0057 | {'duplicate_invoice': 160, 'fx_misconversion': 160, 'period_cutoff': 140, 'unallocated_payment': 140} | {'duplicate_invoice': 14, 'fx_misconversion': 21, 'period_cutoff': 17, 'unallocated_payment': 18} |
| oracle | 0.750 | 0.750 | 1.000 | +1.000 | 1.0 | 1.0 | 1.0 | 0.0003 | - | - |
| expert | 0.750 | 0.750 | 1.000 | +0.968 | 0.9732 | 0.9663 | 17.0 | 0.0115 | - | - |

Precision/recall are 0 by definition when their denominator is 0 (e.g. clean books answered with no findings), so mean P/R are below 1 even for the oracle; F1 and return follow the spec (empty truth + empty answer => F1 = 1).

