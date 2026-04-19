"""Market normalization and data-quality checks for Polymarket signals."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional


TradeSide = Literal["YES", "NO"]


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class DataQualityIssue:
    ticker: str
    condition_id: Optional[str]
    reason: str
    detail: str


@dataclass(frozen=True)
class NormalizedMarket:
    ticker: str
    condition_id: str
    question: str
    market_type: str
    yes_price: Optional[float]
    no_price: Optional[float]
    liquidity: float
    volume_24h: float
    trade_count: int
    sentiment_score: Optional[float]
    active: bool
    end_date: Optional[date] = None
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def quote_for(self, side: TradeSide) -> Optional[float]:
        return self.yes_price if side == "YES" else self.no_price

    def token_id_for(self, side: TradeSide) -> Optional[str]:
        return self.yes_token_id if side == "YES" else self.no_token_id


@dataclass(frozen=True)
class MarketQuote:
    ticker: str
    condition_id: str
    side: TradeSide
    reference_price: float
    token_id: Optional[str]
    source: str = "adanos_snapshot"


class MarketResolver:
    """Normalize Adanos market payloads and reject unsafe/stale market data."""

    def resolve(
        self,
        ticker: str,
        data: dict[str, Any],
        *,
        now: Optional[datetime] = None,
        require_token_ids: bool = False,
    ) -> tuple[Optional[NormalizedMarket], Optional[DataQualityIssue]]:
        ticker = ticker.strip().upper()
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        condition_id = str(data.get("condition_id") or "").strip()

        if not ticker:
            return None, DataQualityIssue("", condition_id or None, "invalid_ticker", "missing ticker")
        if not condition_id:
            return None, DataQualityIssue(ticker, None, "market_missing_condition_id", "missing condition_id")

        question = str(data.get("question") or "").strip()
        if not question:
            return None, DataQualityIssue(ticker, condition_id, "market_missing_question", "missing question")

        if bool(data.get("closed")) or bool(data.get("archived")):
            return None, DataQualityIssue(ticker, condition_id, "market_closed", "closed or archived")
        if not bool(data.get("active", True)):
            return None, DataQualityIssue(ticker, condition_id, "market_closed", "inactive")

        end_date = parse_market_date(data.get("end_date") or data.get("endDate"))
        if end_date is not None and end_date < now.date():
            return None, DataQualityIssue(ticker, condition_id, "market_closed", f"end_date={end_date.isoformat()}")

        yes_price = optional_float(data.get("yes_price"))
        no_price = optional_float(data.get("no_price"))
        price_issue = validate_probability_price(ticker, condition_id, "yes_price", yes_price)
        if price_issue is not None:
            return None, price_issue
        price_issue = validate_probability_price(ticker, condition_id, "no_price", no_price)
        if price_issue is not None:
            return None, price_issue

        liquidity = as_float(data.get("liquidity"))
        if liquidity < 0:
            return None, DataQualityIssue(ticker, condition_id, "invalid_liquidity", f"liquidity={liquidity:.2f}")

        volume_24h = as_float(data.get("volume_24h"))
        if volume_24h < 0:
            return None, DataQualityIssue(ticker, condition_id, "invalid_volume", f"volume_24h={volume_24h:.2f}")

        trade_count = as_int(data.get("trade_count"))
        if trade_count < 0:
            return None, DataQualityIssue(ticker, condition_id, "invalid_trade_count", f"trade_count={trade_count}")

        yes_token_id, no_token_id = extract_token_ids(data)
        if require_token_ids and (not yes_token_id or not no_token_id):
            return None, DataQualityIssue(ticker, condition_id, "missing_token_id", "YES/NO CLOB token ids unavailable")

        sentiment_score = optional_float(data.get("sentiment_score"))
        if sentiment_score is not None and not -1.0 <= sentiment_score <= 1.0:
            return None, DataQualityIssue(ticker, condition_id, "invalid_sentiment", f"sentiment={sentiment_score:.3f}")

        return (
            NormalizedMarket(
                ticker=ticker,
                condition_id=condition_id,
                question=question,
                market_type=str(data.get("market_type") or "other").strip() or "other",
                yes_price=yes_price,
                no_price=no_price,
                liquidity=liquidity,
                volume_24h=volume_24h,
                trade_count=trade_count,
                sentiment_score=sentiment_score,
                active=True,
                end_date=end_date,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                raw=dict(data),
            ),
            None,
        )


class QuoteAdapter:
    """Return executable-style quote objects from normalized market snapshots."""

    def quote(
        self,
        market: NormalizedMarket,
        side: TradeSide,
        *,
        require_token_id: bool = False,
    ) -> tuple[Optional[MarketQuote], Optional[DataQualityIssue]]:
        token_id = market.token_id_for(side)
        if require_token_id and not token_id:
            return None, DataQualityIssue(
                market.ticker,
                market.condition_id,
                "missing_token_id",
                f"{side} token id unavailable",
            )

        price = market.quote_for(side)
        if price is None:
            return None, DataQualityIssue(market.ticker, market.condition_id, "missing_quote", side)
        if price < 0.0 or price > 1.0:
            return None, DataQualityIssue(
                market.ticker,
                market.condition_id,
                "invalid_quote",
                f"{side}={price:.4f}",
            )

        return (
            MarketQuote(
                ticker=market.ticker,
                condition_id=market.condition_id,
                side=side,
                reference_price=price,
                token_id=token_id,
            ),
            None,
        )


def optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_probability_price(
    ticker: str,
    condition_id: str,
    field_name: str,
    value: Optional[float],
) -> Optional[DataQualityIssue]:
    if value is None:
        return None
    if 0.0 <= value <= 1.0:
        return None
    return DataQualityIssue(ticker, condition_id, "price_out_of_range", f"{field_name}={value:.4f}")


def parse_market_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    for candidate in (text, text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.date()
        except ValueError:
            try:
                return date.fromisoformat(candidate)
            except ValueError:
                continue
    return None


def extract_token_ids(data: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    tokens = parse_jsonish(data.get("tokens"))
    if isinstance(tokens, list):
        yes, no = token_ids_from_tokens(tokens)
        if yes or no:
            return yes, no

    outcomes = parse_jsonish(data.get("outcomes"))
    token_ids = parse_jsonish(
        data.get("clob_token_ids")
        or data.get("clobTokenIds")
        or data.get("token_ids")
        or data.get("tokenIds")
    )
    if isinstance(outcomes, list) and isinstance(token_ids, list):
        yes: Optional[str] = None
        no: Optional[str] = None
        for outcome, token_id in zip(outcomes, token_ids):
            label = str(outcome).strip().lower()
            token = str(token_id).strip()
            if label == "yes":
                yes = token or None
            elif label == "no":
                no = token or None
        if yes or no:
            return yes, no

    if isinstance(token_ids, list) and len(token_ids) >= 2:
        return str(token_ids[0]).strip() or None, str(token_ids[1]).strip() or None

    return None, None


def token_ids_from_tokens(tokens: list[Any]) -> tuple[Optional[str], Optional[str]]:
    yes: Optional[str] = None
    no: Optional[str] = None
    for token in tokens:
        if not isinstance(token, dict):
            continue
        label = str(token.get("outcome") or token.get("name") or "").strip().lower()
        token_id = str(token.get("token_id") or token.get("tokenId") or token.get("id") or "").strip()
        if label == "yes":
            yes = token_id or None
        elif label == "no":
            no = token_id or None
    return yes, no


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value
