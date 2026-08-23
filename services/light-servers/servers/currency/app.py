from fastmcp import FastMCP
from typing import Dict, List, Optional

mcp = FastMCP("CurrencyServer")


CURRENCIES: Dict[str, Dict[str, str]] = {
    "USD": {"name": "US Dollar", "symbol": "$"},
    "EUR": {"name": "Euro", "symbol": "\u20ac"},
    "GBP": {"name": "British Pound", "symbol": "\u00a3"},
    "JPY": {"name": "Japanese Yen", "symbol": "\u00a5"},
    "CNY": {"name": "Chinese Yuan", "symbol": "\u00a5"},
    "INR": {"name": "Indian Rupee", "symbol": "\u20b9"},
    "KRW": {"name": "South Korean Won", "symbol": "\u20a9"},
    "CAD": {"name": "Canadian Dollar", "symbol": "C$"},
    "AUD": {"name": "Australian Dollar", "symbol": "A$"},
    "CHF": {"name": "Swiss Franc", "symbol": "CHF"},
    "SEK": {"name": "Swedish Krona", "symbol": "kr"},
    "NOK": {"name": "Norwegian Krone", "symbol": "kr"},
    "DKK": {"name": "Danish Krone", "symbol": "kr"},
    "SGD": {"name": "Singapore Dollar", "symbol": "S$"},
    "HKD": {"name": "Hong Kong Dollar", "symbol": "HK$"},
    "NZD": {"name": "New Zealand Dollar", "symbol": "NZ$"},
    "MXN": {"name": "Mexican Peso", "symbol": "$"},
    "BRL": {"name": "Brazilian Real", "symbol": "R$"},
    "ZAR": {"name": "South African Rand", "symbol": "R"},
    "TRY": {"name": "Turkish Lira", "symbol": "\u20ba"},
    "RUB": {"name": "Russian Ruble", "symbol": "\u20bd"},
}

RATES_TO_USD: Dict[str, float] = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067, "CNY": 0.14,
    "INR": 0.012, "KRW": 0.00076, "CAD": 0.74, "AUD": 0.66, "CHF": 1.14,
    "SEK": 0.095, "NOK": 0.093, "DKK": 0.145, "SGD": 0.75, "HKD": 0.128,
    "NZD": 0.61, "MXN": 0.058, "BRL": 0.20, "ZAR": 0.055, "TRY": 0.034, "RUB": 0.011,
}

HISTORICAL: Dict[str, Dict[str, float]] = {
    "2020-01-01": {"EUR": 1.12, "GBP": 1.32, "JPY": 0.0092, "INR": 0.014},
    "2022-01-01": {"EUR": 1.14, "GBP": 1.35, "JPY": 0.0087, "INR": 0.013},
    "2024-01-01": {"EUR": 1.10, "GBP": 1.27, "JPY": 0.0071, "INR": 0.012},
    "2026-01-01": {"EUR": 1.08, "GBP": 1.27, "JPY": 0.0067, "INR": 0.012},
}

COUNTRY_CURRENCY: Dict[str, List[str]] = {
    "US": ["USD"], "GB": ["GBP"], "JP": ["JPY"], "CN": ["CNY"], "IN": ["INR"],
    "KR": ["KRW"], "CA": ["CAD"], "AU": ["AUD"], "CH": ["CHF"], "SE": ["SEK"],
    "NO": ["NOK"], "DK": ["DKK"], "SG": ["SGD"], "HK": ["HKD"], "NZ": ["NZD"],
    "MX": ["MXN"], "BR": ["BRL"], "ZA": ["ZAR"], "TR": ["TRY"], "RU": ["RUB"],
    "DE": ["EUR"], "FR": ["EUR"], "IT": ["EUR"], "ES": ["EUR"], "NL": ["EUR"],
    "PT": ["EUR"], "GR": ["EUR"], "IE": ["EUR"], "AT": ["EUR"], "BE": ["EUR"],
    "FI": ["EUR"], "LU": ["EUR"],
}


def _rate_to_usd(code: str, date: Optional[str] = None) -> float:
    code = code.upper()
    if date and date in HISTORICAL and code in HISTORICAL[date]:
        return HISTORICAL[date][code]
    if code not in RATES_TO_USD:
        raise KeyError(f"unknown currency: {code}")
    return RATES_TO_USD[code]


@mcp.tool
async def convert(amount: float, from_currency: str, to_currency: str, date: Optional[str] = None) -> float:
    """Convert `amount` from `from_currency` to `to_currency`. Uses `date` snapshot if given."""
    usd = amount * _rate_to_usd(from_currency, date)
    return usd / _rate_to_usd(to_currency, date)


@mcp.tool
async def get_rate(from_currency: str, to_currency: str, date: Optional[str] = None) -> float:
    """Return the exchange rate: how many `to_currency` units equal 1 unit of `from_currency`."""
    return _rate_to_usd(from_currency, date) / _rate_to_usd(to_currency, date)


@mcp.tool
async def historical_rate(from_currency: str, to_currency: str, date: str) -> float:
    """Return the exchange rate on a specific `date` snapshot (falls back to latest)."""
    return await get_rate.__wrapped__(from_currency, to_currency, date)


@mcp.tool
async def inverse_rate(from_currency: str, to_currency: str, date: Optional[str] = None) -> float:
    """Return the inverse of the exchange rate from `from_currency` to `to_currency`."""
    return 1.0 / await get_rate.__wrapped__(from_currency, to_currency, date)


@mcp.tool
async def list_currencies() -> List[str]:
    """Return the sorted list of supported ISO currency codes."""
    return sorted(CURRENCIES.keys())


@mcp.tool
async def currency_info(code: str) -> Dict[str, str]:
    """Return {code, name, symbol} for the given ISO currency code."""
    code = code.upper()
    if code not in CURRENCIES:
        raise KeyError(f"unknown currency: {code}")
    return {"code": code, **CURRENCIES[code]}


@mcp.tool
async def format_amount(amount: float, code: str, decimals: int = 2) -> str:
    """Format `amount` with `code`'s symbol and grouping (naive: en-US style)."""
    info = await currency_info.__wrapped__(code)
    return f"{info['symbol']}{amount:,.{decimals}f}"


@mcp.tool
async def add_amounts(a: float, code_a: str, b: float, code_b: str, target: str, date: Optional[str] = None) -> float:
    """Convert both amounts to `target` currency and return the sum."""
    left = await convert.__wrapped__(a, code_a, target, date)
    right = await convert.__wrapped__(b, code_b, target, date)
    return left + right


@mcp.tool
async def convert_batch(amounts: List[float], from_currency: str, to_currency: str, date: Optional[str] = None) -> List[float]:
    """Convert a list of amounts from `from_currency` to `to_currency` in one call."""
    rate = await get_rate.__wrapped__(from_currency, to_currency, date)
    return [a * rate for a in amounts]


@mcp.tool
async def currencies_by_country(country_code: str) -> List[str]:
    """Return the list of ISO currency codes used in the given ISO 2-letter country code."""
    return COUNTRY_CURRENCY.get(country_code.upper(), [])


@mcp.tool
async def major_currencies() -> List[str]:
    """Return the list of major reserve currencies (USD, EUR, GBP, JPY, CHF, CNY, CAD, AUD)."""
    return ["USD", "EUR", "GBP", "JPY", "CHF", "CNY", "CAD", "AUD"]


@mcp.tool
async def convert_to_usd(amount: float, from_currency: str, date: Optional[str] = None) -> float:
    """Convenience: convert `amount` in `from_currency` to USD."""
    return await convert.__wrapped__(amount, from_currency, "USD", date)


@mcp.tool
async def historical_dates() -> List[str]:
    """Return the sorted list of snapshot dates for which historical rates are available."""
    return sorted(HISTORICAL.keys())


@mcp.tool
async def compare_pair(pair: str, date: Optional[str] = None) -> Dict:
    """Return quote data for a currency pair like 'EUR/USD' at optional `date` snapshot."""
    if "/" not in pair:
        raise ValueError("pair must be like BASE/QUOTE")
    base, quote = pair.upper().split("/")
    rate = await get_rate.__wrapped__(base, quote, date)
    return {"pair": f"{base}/{quote}", "rate": rate, "inverse": 1.0 / rate, "date": date or "latest"}
