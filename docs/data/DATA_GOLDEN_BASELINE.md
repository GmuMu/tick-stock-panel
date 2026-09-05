# Cross-Provider Golden Baseline

## Purpose

`TASK-0204` uses a small, deterministic fixture to prove that provider-specific
field names and units converge to the same internal contract. The tests are
offline: they do not require a TickFlow key, a Fuyao key, a running free-stockdb
service, or network access.

Fixture: `backend/tests/fixtures/provider_golden/market.json`

## Scope

The baseline uses symbol `600519.SH` and the following fixed observations:

| Dataset | Contract covered |
| --- | --- |
| `daily` | symbol/date aliases, raw OHLC, volume in lots, amount in CNY |
| `minute` | datetime wall-clock, OHLC, volume in lots, amount in CNY |
| `realtime` | symbol aliases, prices, previous close, decimal change ratio, volume in lots |
| `adj_factor` | event date and non-cumulative per-event factor |
| `financial` | `period_end` versus `announce_date`, amount and per-share values |

The fixture date `2026-09-04` is in the past relative to the current baseline
date `2026-09-05`; it is intentionally not a live market assertion.

## Canonical Rules

- Symbols are stored as `CODE.EXCHANGE`, for example `600519.SH`.
- Dates are Beijing calendar dates.
- Datetimes are Beijing wall-clock values at provider boundaries.
- Prices are CNY per share.
- Amounts are CNY yuan.
- A-share volume is stored in lots; provider values in shares are divided by 100
  and floored.
- Ratios are stored as decimals; `0.0007142857` means about `0.07142857%`.
- Daily K lines are raw, unadjusted prices. The project applies forward
  adjustment later from local `ex_factor` events.
- `ex_factor` is a single event ratio, not a cumulative factor chain.
- Financial `period_end` identifies the reporting period, while
  `announce_date` identifies when the observation became public. Tests must not
  replace one with the other.

## Acceptance

The golden tests must:

1. Invoke each adapter with fixture-shaped provider responses.
2. Compare canonical identity and numeric fields across providers.
3. Assert unit conversions explicitly, especially shares-to-lots and
   percent-to-decimal.
4. Assert that the Fuyao event formula produces the same factor as direct
   provider factors.
5. Assert that financial rows retain both reporting period and announcement
   date.
6. Remain deterministic and network-free.

Small floating-point differences use field-specific tolerances documented in
the test helper; identity fields and volumes are exact.
