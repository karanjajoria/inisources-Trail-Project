"""
currency_tracker.py
====================
Fetches today's and yesterday's USD exchange rates from the Frankfurter API
(https://www.frankfurter.app — free, no API key required), calculates percentage
change for a set of target currencies, saves results to CSV, and writes a log file.

Usage:
    python currency_tracker.py

Output files (written to the same directory as this script):
    currency_rates_YYYY-MM-DD.csv   — today's snapshot
    currency_tracker.log            — running log file (appended on each run)
"""

import csv
import logging
import os
import sys
from datetime import date, timedelta

import requests  # pip install requests

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Base currency for all exchange rates
BASE_CURRENCY = "USD"

# Target currencies to track
TARGET_CURRENCIES = ["INR", "AED", "USD", "EUR", "GBP", "BRL", "MXN"]

# A rate move larger than this (in %) is flagged as significant
SIGNIFICANCE_THRESHOLD = 0.5

# Free API — no key needed, returns rates relative to any base currency
API_BASE_URL = "https://api.frankfurter.app"

# Output paths (same folder as this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "currency_tracker.log")
CSV_FILE = os.path.join(SCRIPT_DIR, f"currency_rates_{date.today()}.csv")


# ---------------------------------------------------------------------------
# LOGGING SETUP
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    """
    Configure a logger that writes to both the log file and stdout.
    Each run appends to the existing log so history is preserved.
    """
    logger = logging.getLogger("currency_tracker")
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers if the module is somehow imported twice
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — always append
    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# API HELPERS
# ---------------------------------------------------------------------------

def fetch_rates(target_date: date, logger: logging.Logger) -> dict[str, float]:
    """
    Fetch exchange rates from the Frankfurter API for a specific date.

    Args:
        target_date: The date for which rates are required.
        logger:      Logger instance for recording activity.

    Returns:
        A dict mapping currency code → rate  (e.g. {"INR": 83.42, ...}).
        The base currency (USD) is injected as 1.0 by the caller.

    Raises:
        requests.RequestException: Propagated if the request fails completely.
    """
    # Build endpoint: /YYYY-MM-DD?from=USD&to=INR,AED,...
    # Exclude USD itself from the query string (API won't return base→base)
    currencies_to_fetch = [c for c in TARGET_CURRENCIES if c != BASE_CURRENCY]
    symbols = ",".join(currencies_to_fetch)

    url = f"{API_BASE_URL}/{target_date.isoformat()}"
    params = {"from": BASE_CURRENCY, "to": symbols}

    logger.debug(f"GET {url} | params={params}")

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()          # raises HTTPError on 4xx/5xx
    except requests.exceptions.Timeout:
        logger.error(f"Request timed out for date {target_date}")
        raise
    except requests.exceptions.HTTPError as exc:
        logger.error(f"HTTP error for date {target_date}: {exc}")
        raise
    except requests.exceptions.RequestException as exc:
        logger.error(f"Network error for date {target_date}: {exc}")
        raise

    data = response.json()

    # Frankfurter returns: {"amount": 1, "base": "USD", "date": "...", "rates": {...}}
    rates: dict[str, float] = data.get("rates", {})

    if not rates:
        logger.warning(f"Empty rates payload for date {target_date}. Response: {data}")

    logger.info(f"Fetched {len(rates)} rates for {target_date} (base: {BASE_CURRENCY})")
    return rates


# ---------------------------------------------------------------------------
# CALCULATION
# ---------------------------------------------------------------------------

def calculate_changes(
    today_rates: dict[str, float],
    yesterday_rates: dict[str, float],
    logger: logging.Logger,
) -> list[dict]:
    """
    Compare today's and yesterday's rates, calculate percentage change,
    and flag significant movements.

    Args:
        today_rates:     Currency → rate for today.
        yesterday_rates: Currency → rate for yesterday.
        logger:          Logger instance.

    Returns:
        A list of dicts, one per tracked currency, ready for CSV output.
    """
    results = []

    for currency in TARGET_CURRENCIES:
        # USD/USD is always 1.0 — injected directly, not from the API
        if currency == BASE_CURRENCY:
            today_rate = 1.0
            yesterday_rate = 1.0
        else:
            today_rate = today_rates.get(currency)
            yesterday_rate = yesterday_rates.get(currency)

        # Skip if either rate is missing (API gap, weekend, holiday)
        if today_rate is None or yesterday_rate is None:
            logger.warning(
                f"Skipping {currency}: missing data "
                f"(today={today_rate}, yesterday={yesterday_rate})"
            )
            continue

        # Percentage change = ((today - yesterday) / yesterday) × 100
        if yesterday_rate == 0:
            logger.warning(f"Skipping {currency}: yesterday's rate is 0 (division by zero)")
            continue

        pct_change = ((today_rate - yesterday_rate) / yesterday_rate) * 100

        # Flag moves greater than the significance threshold
        significant = abs(pct_change) > SIGNIFICANCE_THRESHOLD

        results.append(
            {
                "currency": currency,
                "today_rate": round(today_rate, 6),
                "yesterday_rate": round(yesterday_rate, 6),
                "percentage_change": round(pct_change, 4),
                "significant": "TRUE" if significant else "FALSE",
            }
        )

        logger.debug(
            f"{currency}: today={today_rate:.6f}  yesterday={yesterday_rate:.6f}  "
            f"change={pct_change:+.4f}%  significant={significant}"
        )

    return results


# ---------------------------------------------------------------------------
# CSV OUTPUT
# ---------------------------------------------------------------------------

def save_to_csv(rows: list[dict], filepath: str, logger: logging.Logger) -> None:
    """
    Write the results list to a CSV file.

    Args:
        rows:     List of result dicts from calculate_changes().
        filepath: Destination file path.
        logger:   Logger instance.
    """
    if not rows:
        logger.warning("No data rows to write — CSV not created.")
        return

    fieldnames = ["currency", "today_rate", "yesterday_rate", "percentage_change", "significant"]

    try:
        with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"CSV saved → {filepath}  ({len(rows)} rows)")

    except OSError as exc:
        logger.error(f"Failed to write CSV: {exc}")
        raise


# ---------------------------------------------------------------------------
# MAIN ORCHESTRATION
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Entry point — orchestrates fetching, calculating, and saving.
    Logs a clear success or failure summary at the end of every run.
    """
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("Currency Tracker — run started")
    logger.info(f"Base currency : {BASE_CURRENCY}")
    logger.info(f"Tracking      : {', '.join(TARGET_CURRENCIES)}")

    today = date.today()
    yesterday = today - timedelta(days=1)

    try:
        # Step 1 — fetch today's rates
        logger.info(f"Fetching rates for TODAY     ({today})")
        today_rates = fetch_rates(today, logger)

        # Step 2 — fetch yesterday's rates
        logger.info(f"Fetching rates for YESTERDAY ({yesterday})")
        yesterday_rates = fetch_rates(yesterday, logger)

        # Step 3 — calculate percentage changes
        logger.info("Calculating percentage changes …")
        results = calculate_changes(today_rates, yesterday_rates, logger)

        # Step 4 — save CSV
        save_to_csv(results, CSV_FILE, logger)

        # Summary
        significant_count = sum(1 for r in results if r["significant"] == "TRUE")
        logger.info(
            f"Run complete. Processed {len(results)} currencies. "
            f"Significant moves: {significant_count}."
        )

    except requests.RequestException:
        # Already logged in fetch_rates(); just mark the run as failed
        logger.error("Run FAILED due to API error. See details above.")
        sys.exit(1)

    except Exception as exc:
        logger.exception(f"Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()