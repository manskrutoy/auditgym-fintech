# Measured failure analysis — local_holdout (20 episodes, eval mode)

Every false positive and false negative of each baseline is attributed to the concrete cause (evaluator-side, using truth, provenance mutations and per-document distractor tags).

## random

| false positive cause | count | example |
|---|---|---|
| allocation claim on an applied payment | 9 | `ep-064290a24986: unallocated_payment ['PAY-638902']` |
| duplicate claim without identical documents | 6 | `ep-064290a24986: duplicate_invoice ['CUST-32350']` |
| unknown document | 4 | `ep-0d83586844a9: fx_misconversion ['CUST-53807']` |
| cut-off claim on a correctly dated posting | 4 | `ep-f34f524094af: period_cutoff ['DOC-8154e0a2']` |
| trap: no rate that day (weekend/holiday) -> previous business day | 2 | `ep-e6f087fa84af: fx_misconversion ['INV-750845']` |

| missed issue (type, injected variant) | count |
|---|---|
| duplicate_invoice | 10 |
| period_cutoff | variant=early | 8 |
| period_cutoff | variant=late | 7 |
| period_cutoff | variant=early | interaction=cutoff_fx_boundary | 6 |
| unallocated_payment | variant=partial | 6 |
| unallocated_payment | variant=missing | 6 |
| unallocated_payment | variant=partial | interaction=fx_partial_payment | 5 |
| fx_misconversion | wrong_date_rule=next_day_value_date | document=invoice | 4 |
| fx_misconversion | wrong_date_rule=posting_date_minus_1 | document=invoice | interaction=cutoff_fx_boundary | 3 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=payment | 3 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=invoice | 3 |
| fx_misconversion | wrong_date_rule=posting_date | document=invoice | interaction=cutoff_fx_boundary | 3 |
| fx_misconversion | wrong_date_rule=next_day_value_date | document=payment | interaction=fx_partial_payment | 3 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | interaction=fx_partial_payment | 2 |
| fx_misconversion | wrong_date_rule=period_end_rate | document=invoice | 2 |
| fx_misconversion | wrong_date_rule=previous_day | document=invoice | 1 |
| fx_misconversion | wrong_date_rule=due_date | document=invoice | 1 |

## reconciler

| false positive cause | count | example |
|---|---|---|
| trap: printed/UTC date differs from company-local date | 37 | `ep-064290a24986: fx_misconversion ['INV-903251']` |
| trap: legitimate recurring / repeated amount | 36 | `ep-e6f087fa84af: duplicate_invoice ['INV-001445', 'INV-438010']` |
| trap: period boundary in another time zone | 19 | `ep-e6f087fa84af: period_cutoff ['INV-854093']` |

| missed issue (type, injected variant) | count |
|---|---|
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=payment | 3 |
| fx_misconversion | wrong_date_rule=next_day_value_date | document=payment | interaction=fx_partial_payment | 3 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | interaction=fx_partial_payment | 2 |
| period_cutoff | variant=early | 1 |

## flag_all

| false positive cause | count | example |
|---|---|---|
| cut-off claim on a correctly dated posting | 140 | `ep-e6f087fa84af: period_cutoff ['INV-777486']` |
| duplicate claim without identical documents | 131 | `ep-e6f087fa84af: duplicate_invoice ['INV-777486']` |
| allocation claim on an applied payment | 118 | `ep-e6f087fa84af: unallocated_payment ['INV-185956', 'PAY-511128']` |
| trap: no rate that day (weekend/holiday) -> previous business day | 106 | `ep-e6f087fa84af: fx_misconversion ['INV-777486']` |
| fx claim on a correctly converted document | 45 | `ep-064290a24986: fx_misconversion ['INV-062455']` |
| trap: legitimate recurring / repeated amount | 29 | `ep-e6f087fa84af: duplicate_invoice ['INV-438010']` |
| trap: legitimate unapplied receipt / advance / refund | 20 | `ep-e6f087fa84af: unallocated_payment ['INV-872385', 'PAY-268118']` |
| trap: printed/UTC date differs from company-local date | 9 | `ep-e6f087fa84af: fx_misconversion ['INV-494258']` |
| right issue, incomplete evidence | 1 | `ep-db81876cd2ca: unallocated_payment ['INV-742303', 'PAY-159759']` |
| partially right ids (guessed/incomplete affected_ids) | 1 | `ep-ac446d7f0fd1: unallocated_payment ['INV-971614', 'PAY-070966']` |

| missed issue (type, injected variant) | count |
|---|---|
| duplicate_invoice | 10 |
| period_cutoff | variant=early | 8 |
| period_cutoff | variant=late | 7 |
| period_cutoff | variant=early | interaction=cutoff_fx_boundary | 6 |
| unallocated_payment | variant=partial | 6 |
| unallocated_payment | variant=missing | 6 |
| unallocated_payment | variant=partial | interaction=fx_partial_payment | 5 |
| fx_misconversion | wrong_date_rule=next_day_value_date | document=invoice | 4 |
| fx_misconversion | wrong_date_rule=posting_date_minus_1 | document=invoice | interaction=cutoff_fx_boundary | 3 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=payment | 3 |
| fx_misconversion | wrong_date_rule=stale_rate_0d | document=invoice | 3 |
| fx_misconversion | wrong_date_rule=posting_date | document=invoice | interaction=cutoff_fx_boundary | 3 |
| fx_misconversion | wrong_date_rule=next_day_value_date | document=payment | interaction=fx_partial_payment | 3 |
| fx_misconversion | wrong_date_rule=previous_day | document=payment | interaction=fx_partial_payment | 2 |
| fx_misconversion | wrong_date_rule=period_end_rate | document=invoice | 2 |
| fx_misconversion | wrong_date_rule=previous_day | document=invoice | 1 |
| fx_misconversion | wrong_date_rule=due_date | document=invoice | 1 |

## oracle

No false positives, no misses.

## expert

No false positives, no misses.

