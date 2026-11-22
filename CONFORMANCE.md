# Соответствие ТЗ: пункт → реализация → доказательство

Таблица для жюри. Для каждого требования указано, где оно реализовано и какой тест или шаг
`python -m auditgym check` это подтверждает. Тесты лежат в `tests/` и запускаются внутри `check`.

## 02. Сложность

| требование | реализация | доказательство |
|---|---|---|
| ≥ 4 независимо настраиваемых типа ошибок | `config.errors.{duplicate_invoice, unallocated_payment, fx_misconversion, period_cutoff}`, `auditgym/injectors.py` | `test_each_type_independently_configurable` |
| ≥ 2 сценария взаимодействующих ошибок | `fx_partial_payment`, `cutoff_fx_boundary` (`injectors.py`) | `test_interactions` |
| Чистые компании и корректные отвлекающие случаи | пресет `clean`; повторяющиеся суммы, разбитые и мульти-платежи, возвраты, авансы, курсы выходных, граничные документы в чужих поясах (`world.py`) | `test_clean_episodes_have_distractors_and_no_issues`, `reports/failure_analysis.md` |
| Сначала скрытая история, затем документы и ошибки с причинным изменением | `world.py` → `injectors.py` → `posting.py`; `provenance.json`: `mutations`, `ledger_diff_vs_clean`; `private/clean_ledger.csv` | `check_declared_changes`, `verify.check_clean_ledger`, шаг 3 `check` |
| Эталон — реальное расхождение с доступными доказательствами | `generator._amount`, `evidence_sets` только из публичных ID | `verify.verify_issue` для каждого набора, шаг 3 `check` |
| Вариативность имён, ID, порядка, сумм, валют, поясов, сочетаний | случайные ID, 8 валют (экспоненты 0/2/3), 8 поясов компании, 11 поясов документов, `order_seed`, 2 режима округления | `test_id_and_order_seeds_keep_the_world`, `test_timestamp_and_id_artefacts` |
| Простые трюки не работают, задача решаема | наивная сверка против эксперта | `test_simple_tricks_fail_but_task_is_solvable`, таблица baseline в `reports/check_report.md` |

## 03. Эпизод и формат данных

| требование | реализация | доказательство |
|---|---|---|
| manifest.json: schema_version, episode_id, base_currency, period_start/end, timezone, counts, rounding | `generator._render` | `schemas/manifest.schema.json`, `verify.check_schema` |
| Время ISO-8601 со смещением, деньги в целых минимальных единицах, FX-курсы десятичными строками | `timeutil.iso`, `money.py` | `test_value_formats` |
| ledger.csv, invoices.jsonl, payments.jsonl, fx.csv, policy.json | `episode.save` (в fx.csv добавлен ключ `fx_id` для ссылок в доказательствах) | `test_save_load_roundtrip` |
| Отсутствующие ссылки — явный `null` | `null` в CSV, `null` в JSON | `test_value_formats` |
| Закрытые truth.json и provenance.json, агент не видит seed | `private/`; seed только в provenance | `test_no_closed_data_in_any_observation`, шаг 6 `check` |
| Оценщик вне процесса агента, записи только для чтения | `evaluator.py` + `worker.py` (отдельный процесс), наблюдения — копии | `test_worker_matches_in_process`, `test_observations_are_copies` |

## 04. Наблюдения, действия, завершение

| требование | реализация | доказательство |
|---|---|---|
| `reset(seed, config) → (obs, info)`, первое наблюдение: задача, manifest, политика, бюджет | `AuditEnv.reset` | `test_reset_returns_observation_and_info` |
| `step → (obs, reward, terminated, truncated, info)` | `AuditEnv.step` | все тесты `test_env_contract.py` |
| Воспроизводимость seed/config/версии/действий, изоляция reset | детерминированные RNG-потоки на sha256 | `test_same_seed_same_records_and_transitions`, `test_reset_isolates_state`, шаги 2 и 5 `check` |
| list_records / get_record / get_document / calculator / submit; страница ≤ 50, стабильные курсоры | `env._t_*` | `test_page_limit_and_stable_cursor`, `test_cursor_reaches_end`, `test_get_record_and_document` |
| Калькулятор: только арифметика | `calculator.py` (AST, Decimal) | `test_calculator_arithmetic_only` |
| Неизвестный ID или действие: ограниченная ошибка, тратит шаг | `ToolError` | `test_errors_are_bounded_and_consume_steps` |
| ≤ 100 шагов включая submit; лимит шагов или времени → truncated и пустой ответ | `env._finish` | `test_step_limit_truncates_with_empty_answer`, `test_submit_at_step_100_is_allowed`, `test_time_limit_truncates`, `test_timeout_truncates` |
| Награда по ходу 0; терминальная только в train; в eval остаётся у оценщика | `mode="train"/"eval"` | `test_eval_mode_withholds_reward` |

## 05. Выводы и награда

| требование | реализация | доказательство |
|---|---|---|
| Формат findings и лимиты 30 / 10 / 1000 | `matcher.validate_submission`, `schemas/findings.schema.json` | `test_invalid_structures_give_minus_one`, `test_limits_exactly_allowed` |
| Неверная структура → −1 и запись в журнал оценщика | `reward.grade`, `env.evaluator_log` | `test_invalid_structure_ends_with_minus_one` |
| Взаимно однозначное сопоставление: тип, канонические ID, сумма в допуске, валюта, полный набор доказательств | `matcher.compatible`, `matcher.match` (максимальное паросочетание) | `test_maximum_one_to_one`, `test_guessed_ids_do_not_match`, `test_unsupported_evidence_does_not_match`, `test_currency_must_match`, `test_amount_tolerance`, `test_type_must_match` |
| Открытый код нормализации, допусков и выбора при неоднозначности | docstring `matcher.py` | `test_normalisation`, `test_validate_normalises` |
| P, R, F1 и крайние случаи | `reward.metrics` | `test_edge_cases` |
| Награда = clip(2·F1 − 1 − 0.002·steps); экспериментальная — отдельно | `reward.shared_reward`, `reward.experimental_reward` | `test_reward_formula_and_clip` |
| Верный ответ лучше молчания; молчание лучше ложных обвинений; дубли без выгоды; «пометить всё» плохо; шаги различают слабо | — | `test_full_correct_answer_beats_silence_on_erroneous_books`, `test_silence_beats_false_accusations_on_clean_books`, `test_duplicates_give_no_benefit`, `test_flag_everything_scores_badly`, `test_step_savings_only_slightly_separate_equal_answers` |
| Повторная отправка, неверный ввод, тайм-аут | — | `test_after_terminal_nothing_changes`, `test_errors_are_bounded_and_consume_steps`, `test_time_limit_truncates` |
| Награда не зависит от убедительного текста | explanation не оценивается | `test_explanation_is_not_scored` |

## 06. Закрытая проверка

| требование | реализация | доказательство |
|---|---|---|
| Политики: случайная с фиксированным seed, простая сверка, «пометить всё», oracle только для оценщика | `policies/scripted.py`: `RandomExplorer`, `SimpleReconciler`, `FlagAll`, `Oracle` | `test_four_baseline_adapters`, шаг 4 `check` |
| 20 эпизодов (5 чистых, 5 с взаимодействиями) и 20 парных проверок (порядок и ID) | `configs/local_holdout.json`, `cli.paired_checks` (+ перевод поясов, `id_seed`/`order_seed`) | шаги 4 и 5 `check`, `test_relabel_preserves_oracle_and_expert`, `test_reexpressed_offsets_keep_truth_and_answers` |

## 07 и 09. Сдача

| требование | где |
|---|---|
| Генератор, среда, matcher, траектории без эталона, офлайн без GPU, контейнер и одна команда | `auditgym/`, `Dockerfile`, `python -m auditgym check` |
| Исходники, лицензия, зафиксированные зависимости | `LICENSE`, `pyproject.toml`, `requirements.txt` (только stdlib) |
| 10 train + 10 dev эпизодов | `episodes/`, `configs/train.json`, `configs/dev.json`, хэши в `episodes/index.json` |
| Тесты | `tests/` (58) |
| 4 адаптера базовых политик | `auditgym/policies/scripted.py`, `auditgym/worker.py` |
| trajectories.jsonl с episode_id, step, action, observation, reward, terminated, truncated | `trajectories/trajectories.jsonl` (+ поле policy), `test_trajectory_fields` |
| Записка о дизайне и демо | `DESIGN.md`; `python -m auditgym demo`, `reports/demo_dev_09.html` |

## 10. Инженерия и объяснение

| критерий | где |
|---|---|
| Запуск одной командой | `python -m auditgym check`, `docker run ...`, CI `.github/workflows/check.yml` |
| Версии конфигураций | `env_version` / `schema_version` / `policy_version`, `configs/*.json`, полный config в provenance |
| Журналы траекторий | `trajectories/trajectories.jsonl`, `python -m auditgym run` |
| Измеренный разбор сбоев | `reports/failure_analysis.md` (каждый FP привязан к ловушке, каждый FN к варианту ошибки) |
| Честные ограничения | README, раздел 10 |
