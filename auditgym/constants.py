"""Fixed constants of the AuditGym environment contract.

Changing anything here changes the environment version.
"""

ENV_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"

# Episode / tool limits (section 04-05 of the challenge spec)
MAX_STEPS = 100
PAGE_LIMIT = 50
TIME_LIMIT_S = 60.0
MAX_FINDINGS = 30
MAX_EVIDENCE = 10
MAX_AFFECTED = 10
MAX_EXPLANATION = 1000
MAX_ID_LEN = 64
MAX_CALC_LEN = 256
STEP_COST = 0.002

ISSUE_TYPES = (
    "duplicate_invoice",
    "unallocated_payment",
    "fx_misconversion",
    "period_cutoff",
)

INTERACTIONS = (
    "fx_partial_payment",   # partially allocated foreign payment converted at the wrong date
    "cutoff_fx_boundary",   # foreign invoice booked in the wrong period AND at the wrong date's rate
)

TABLES = ("ledger", "invoices", "payments", "fx")
TABLE_KEYS = {
    "ledger": "row_id",
    "invoices": "invoice_id",
    "payments": "payment_id",
    "fx": "fx_id",
}

ACTIONS = ("list_records", "get_record", "get_document", "calculator", "submit")

# Chart of accounts (codes are what appears in ledger.csv)
ACC_CASH = "1000"
ACC_AR = "1100"
ACC_SUSPENSE = "1190"
ACC_ADVANCES = "2300"
ACC_OPENING = "3900"
ACC_REVENUE = "4000"
ACC_FX = "7900"
EXPENSE_ACCOUNTS = {
    "6100": "Rent",
    "6200": "Payroll",
    "6300": "Utilities",
    "6400": "Software subscriptions",
    "6500": "Travel",
    "6600": "Professional services",
}
CHART_OF_ACCOUNTS = {
    ACC_CASH: "Cash at bank",
    ACC_AR: "Accounts receivable",
    ACC_SUSPENSE: "Unapplied receipts (suspense)",
    ACC_ADVANCES: "Customer advances",
    ACC_OPENING: "Opening balance equity",
    ACC_REVENUE: "Revenue",
    ACC_FX: "Realised FX gain/loss",
}
CHART_OF_ACCOUNTS.update(EXPENSE_ACCOUNTS)

# ISO-4217 minor-unit exponents of every currency the generator may use.
CURRENCY_EXPONENTS = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CHF": 2,
    "CNY": 2,
    "KZT": 2,
    "JPY": 0,
    "KWD": 3,
}
# Rough value of one major unit in USD, used only to seed synthetic FX random walks.
USD_VALUE = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "CHF": 1.12,
    "CNY": 0.14,
    "KZT": 0.0021,
    "JPY": 0.0067,
    "KWD": 3.25,
}
BASE_CURRENCIES = ("USD", "EUR", "KZT", "GBP", "JPY")
# Fixed company UTC offsets in minutes (no DST, so no tz database is needed offline).
COMPANY_OFFSETS = (-300, 0, 60, 180, 300, 330, 360, 540)
DOC_OFFSETS = (-480, -300, 0, 60, 120, 180, 300, 360, 480, 540, 600)
