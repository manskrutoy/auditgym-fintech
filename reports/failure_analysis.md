# Measured failure analysis — local_holdout (20 episodes, eval mode)

Every false positive and false negative of each baseline is attributed to the concrete cause (evaluator-side, using truth, provenance mutations and per-document distractor tags).

## random

| false positive cause | count | example |
|---|---|---|
| duplicate claim without identical documents | 9 | `ep-b49b953be0ff: duplicate_invoice ['DOC-d1ca4424']` |
| cut-off claim on a correctly dated posting | 6 | `ep-1b7527ca16cf: period_cutoff ['FX-2024-12-27-EUR-JPY']` |
| unknown document | 6 | `ep-90298cd41fda: fx_misconversion ['ROW-1fb193eb']` |
| allocation claim on an applied payment | 2 | `ep-1b7527ca16cf: unallocated_payment ['CUST-55661']` |
| trap: no rate that day (weekend/holiday) -> previous business day | 2 | `ep-edba1fd0fc8c: fx_misconversion ['PAY-716682']` |
| trap: printed/UTC date differs from company-local date | 1 | `ep-94aa8ffa2fa3: fx_misconversion ['INV-823830']` |
| fx claim on a correctly converted document | 1 | `ep-3287689bcef1: fx_misconversion ['INV-432910']` |

| missed issue (type, injected variant) | count |
|---|---|
| duplicate_invoice | 15 |
| unallocated_payment | variant=missing | 7 |
| unallocated_payment | variant=partial | interaction=fx_partial_payment | 6 |
| period_cutoff | variant=early | 6 |
| period_cutoff | variant=early | interaction=cutoff_fx_boundary | 5 |
| unallocated_payment | variant=partial | 5 |
| period_cutoff | variant=late | 5 |
| fx_misconversion | wrong_date_rule=posting_date | document=invoice | interaction=cutoff_fx_boundary | 4 |
| fx_misconversion | wrong_date_rule=next_day_value_date | document=payment | interaction=fx_partial_payment | 4 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=invoice | 3 |
| fx_misconversion | wrong_date_rule=due_date | document=invoice | 3 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=payment | 3 |
| fx_misconversion | wrong_date_rule=posting_date_minus_1 | document=invoice | interaction=cutoff_fx_boundary | 1 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | interaction=fx_partial_payment | 1 |
| fx_misconversion | wrong_date_rule=period_end_rate | document=invoice | 1 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | 1 |
| fx_misconversion | wrong_date_rule=period_end_rate | document=payment | 1 |
| fx_misconversion | wrong_date_rule=value_date_plus_2 | document=payment | interaction=fx_partial_payment | 1 |
| fx_misconversion | wrong_date_rule=previous_day | document=invoice | 1 |

## reconciler

| false positive cause | count | example |
|---|---|---|
| trap: legitimate recurring / repeated amount | 41 | `ep-1b7527ca16cf: duplicate_invoice ['INV-405852', 'INV-939313']` |
| trap: printed/UTC date differs from company-local date | 39 | `ep-18df55595944: fx_misconversion ['INV-359578']` |
| trap: period boundary in another time zone | 24 | `ep-1b7527ca16cf: period_cutoff ['INV-243801']` |
| right documents, wrong type | 1 | `ep-5e7744992fde: fx_misconversion ['INV-890038']` |

| missed issue (type, injected variant) | count |
|---|---|
| fx_misconversion | wrong_date_rule=next_day_value_date | document=payment | interaction=fx_partial_payment | 4 |
| period_cutoff | variant=early | interaction=cutoff_fx_boundary | 4 |
| fx_misconversion | wrong_date_rule=posting_date | document=invoice | interaction=cutoff_fx_boundary | 3 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=payment | 3 |
| period_cutoff | variant=early | 2 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | interaction=fx_partial_payment | 1 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | 1 |
| fx_misconversion | wrong_date_rule=period_end_rate | document=payment | 1 |
| fx_misconversion | wrong_date_rule=value_date_plus_2 | document=payment | interaction=fx_partial_payment | 1 |

## flag_all

| false positive cause | count | example |
|---|---|---|
| cut-off claim on a correctly dated posting | 140 | `ep-1b7527ca16cf: period_cutoff ['INV-141093']` |
| duplicate claim without identical documents | 129 | `ep-1b7527ca16cf: duplicate_invoice ['INV-141093']` |
| allocation claim on an applied payment | 123 | `ep-1b7527ca16cf: unallocated_payment ['INV-625499', 'PAY-392602']` |
| trap: no rate that day (weekend/holiday) -> previous business day | 107 | `ep-1b7527ca16cf: fx_misconversion ['INV-141093']` |
| fx claim on a correctly converted document | 43 | `ep-1b7527ca16cf: fx_misconversion ['INV-113505']` |
| trap: legitimate recurring / repeated amount | 31 | `ep-1b7527ca16cf: duplicate_invoice ['INV-405852']` |
| trap: legitimate unapplied receipt / advance / refund | 15 | `ep-1b7527ca16cf: unallocated_payment ['INV-641432', 'PAY-022557']` |
| trap: printed/UTC date differs from company-local date | 10 | `ep-b49b953be0ff: fx_misconversion ['INV-859398']` |
| right issue, incomplete evidence | 2 | `ep-0f01f8c85793: unallocated_payment ['INV-772061', 'PAY-850108']` |

| missed issue (type, injected variant) | count |
|---|---|
| duplicate_invoice | 15 |
| unallocated_payment | variant=missing | 7 |
| unallocated_payment | variant=partial | interaction=fx_partial_payment | 6 |
| period_cutoff | variant=early | 6 |
| period_cutoff | variant=early | interaction=cutoff_fx_boundary | 5 |
| unallocated_payment | variant=partial | 5 |
| period_cutoff | variant=late | 5 |
| fx_misconversion | wrong_date_rule=posting_date | document=invoice | interaction=cutoff_fx_boundary | 4 |
| fx_misconversion | wrong_date_rule=next_day_value_date | document=payment | interaction=fx_partial_payment | 4 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=invoice | 3 |
| fx_misconversion | wrong_date_rule=due_date | document=invoice | 3 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=payment | 3 |
| fx_misconversion | wrong_date_rule=posting_date_minus_1 | document=invoice | interaction=cutoff_fx_boundary | 1 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | interaction=fx_partial_payment | 1 |
| fx_misconversion | wrong_date_rule=period_end_rate | document=invoice | 1 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | 1 |
| fx_misconversion | wrong_date_rule=period_end_rate | document=payment | 1 |
| fx_misconversion | wrong_date_rule=value_date_plus_2 | document=payment | interaction=fx_partial_payment | 1 |
| fx_misconversion | wrong_date_rule=previous_day | document=invoice | 1 |

## oracle

No false positives, no misses.

## expert

No false positives, no misses.

