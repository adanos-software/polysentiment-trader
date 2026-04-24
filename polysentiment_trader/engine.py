"""Paper trading engine for Polymarket sentiment signals."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

from polysentiment_trader.market_data import MarketResolver, NormalizedMarket, QuoteAdapter


TradeSide = Literal["YES", "NO"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


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


def isoformat(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def parse_isoformat(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def derive_yes_direction(market_type: str, question: str, ticker: str) -> Optional[int]:
    """Return +1 when YES is bullish for ticker, -1 when bearish."""
    text = f" {question or ''} ".lower()
    ticker_text = ticker.lower()

    if " up or down " in text or " go up or down " in text:
        return 1

    if " outperform " in text:
        ticker_pos = text.find(ticker_text)
        verb_pos = text.find(" outperform ")
        if ticker_pos >= 0 and ticker_pos < verb_pos:
            return 1
        if ticker_pos >= 0 and ticker_pos > verb_pos:
            return -1

    if " underperform " in text:
        ticker_pos = text.find(ticker_text)
        verb_pos = text.find(" underperform ")
        if ticker_pos >= 0 and ticker_pos < verb_pos:
            return -1
        if ticker_pos >= 0 and ticker_pos > verb_pos:
            return 1

    bearish_patterns = (
        " dip ",
        " dips ",
        " drop ",
        " drops ",
        " fall ",
        " falls ",
        " below ",
        " under ",
        " lower ",
        " go down ",
        " down on ",
        " miss ",
        " misses ",
        " bankrupt ",
    )
    if any(pattern in text for pattern in bearish_patterns):
        return -1

    if market_type in {"up_down", "close_above"}:
        return 1
    if market_type == "hit_target":
        return -1 if " low " in text else 1

    bullish_patterns = (
        " close above ",
        " close over ",
        " hit $",
        " hits $",
        " go up ",
        " up on ",
        " higher ",
        " above ",
        " beat ",
        " beats ",
    )
    if any(pattern in text for pattern in bullish_patterns):
        return 1

    return None


@dataclass(frozen=True)
class StrategyConfig:
    """Risk and signal settings for the paper trader."""

    initial_bankroll: float = 1000.0
    max_positions: int = 5
    max_position_pct: float = 0.05
    max_stake: float = 25.0
    min_stake: float = 5.0
    min_buzz_score: float = 35.0
    min_stock_trade_count: int = 10
    min_market_trade_count: int = 1
    min_liquidity: float = 1000.0
    min_abs_sentiment: float = 0.12
    min_edge: float = 0.04
    min_evidence_quality_score: float = 0.45
    min_price: float = 0.05
    max_price: float = 0.65
    kelly_fraction: float = 0.25
    stop_loss_pct: float = -0.20
    take_profit_pct: float = 0.35
    take_profit_cooldown_minutes: int = 240
    max_stop_losses_per_day: int = 2
    allow_stable_trend: bool = True
    require_clob_token_ids: bool = False


@dataclass(frozen=True)
class StockSignal:
    ticker: str
    company_name: Optional[str]
    buzz_score: float
    trend: Optional[str]
    trade_count: int
    sentiment_score: Optional[float]
    total_liquidity: float

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "StockSignal":
        return cls(
            ticker=str(data.get("ticker") or "").strip().upper(),
            company_name=data.get("company_name"),
            buzz_score=as_float(data.get("buzz_score")),
            trend=data.get("trend"),
            trade_count=as_int(data.get("trade_count")),
            sentiment_score=(
                as_float(data.get("sentiment_score"))
                if data.get("sentiment_score") is not None
                else None
            ),
            total_liquidity=as_float(data.get("total_liquidity")),
        )


@dataclass(frozen=True)
class MarketSignal:
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
    end_date: Optional[str] = None
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None

    @classmethod
    def from_api(cls, ticker: str, data: dict[str, Any]) -> "MarketSignal":
        return cls(
            ticker=ticker.upper(),
            condition_id=str(data.get("condition_id") or "").strip(),
            question=str(data.get("question") or "").strip(),
            market_type=str(data.get("market_type") or "other").strip() or "other",
            yes_price=as_float(data.get("yes_price")) if data.get("yes_price") is not None else None,
            no_price=as_float(data.get("no_price")) if data.get("no_price") is not None else None,
            liquidity=as_float(data.get("liquidity")),
            volume_24h=as_float(data.get("volume_24h")),
            trade_count=as_int(data.get("trade_count")),
            sentiment_score=(
                as_float(data.get("sentiment_score"))
                if data.get("sentiment_score") is not None
                else None
            ),
            active=bool(data.get("active", True)),
            end_date=data.get("end_date") or data.get("endDate"),
            yes_token_id=data.get("yes_token_id") or data.get("yesTokenId"),
            no_token_id=data.get("no_token_id") or data.get("noTokenId"),
        )

    @classmethod
    def from_normalized(cls, market: NormalizedMarket) -> "MarketSignal":
        return cls(
            ticker=market.ticker,
            condition_id=market.condition_id,
            question=market.question,
            market_type=market.market_type,
            yes_price=market.yes_price,
            no_price=market.no_price,
            liquidity=market.liquidity,
            volume_24h=market.volume_24h,
            trade_count=market.trade_count,
            sentiment_score=market.sentiment_score,
            active=market.active,
            end_date=market.end_date.isoformat() if market.end_date else None,
            yes_token_id=market.yes_token_id,
            no_token_id=market.no_token_id,
        )

    def quote_for(self, side: TradeSide) -> Optional[float]:
        return self.yes_price if side == "YES" else self.no_price

    def token_id_for(self, side: TradeSide) -> Optional[str]:
        return self.yes_token_id if side == "YES" else self.no_token_id


@dataclass
class Position:
    ticker: str
    condition_id: str
    question: str
    side: TradeSide
    shares: float
    entry_price: float
    current_price: float
    stake: float
    opened_at: str
    thesis: str
    confidence: float
    edge: float
    evidence_quality_score: float = 0.0
    counter_case: tuple[str, ...] = ()
    status: str = "open"
    closed_at: Optional[str] = None
    exit_reason: Optional[str] = None
    realized_pnl: Optional[float] = None

    @property
    def key(self) -> tuple[str, TradeSide]:
        return (self.condition_id, self.side)

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def return_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.current_price - self.entry_price) / self.entry_price

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Position":
        allowed = {field_.name for field_ in fields(cls)}
        payload = {key: value for key, value in data.items() if key in allowed}
        if "current_price" not in payload:
            payload["current_price"] = payload.get("entry_price", 0.0)
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "condition_id": self.condition_id,
            "question": self.question,
            "side": self.side,
            "shares": round(self.shares, 6),
            "entry_price": round(self.entry_price, 4),
            "current_price": round(self.current_price, 4),
            "stake": round(self.stake, 2),
            "opened_at": self.opened_at,
            "thesis": self.thesis,
            "confidence": round(self.confidence, 4),
            "edge": round(self.edge, 4),
            "evidence_quality_score": round(self.evidence_quality_score, 4),
            "counter_case": list(self.counter_case),
            "status": self.status,
            "closed_at": self.closed_at,
            "exit_reason": self.exit_reason,
            "realized_pnl": round(self.realized_pnl, 2) if self.realized_pnl is not None else None,
        }


@dataclass
class Portfolio:
    initial_bankroll: float
    cash: float
    positions: list[Position] = field(default_factory=list)
    closed_positions: list[Position] = field(default_factory=list)
    updated_at: Optional[str] = None

    @classmethod
    def new(cls, initial_bankroll: float) -> "Portfolio":
        return cls(initial_bankroll=initial_bankroll, cash=initial_bankroll)

    @classmethod
    def from_dict(cls, data: dict[str, Any], initial_bankroll: float) -> "Portfolio":
        bankroll = as_float(data.get("initial_bankroll"), initial_bankroll)
        return cls(
            initial_bankroll=bankroll,
            cash=as_float(data.get("cash"), bankroll),
            positions=[
                Position.from_dict(item)
                for item in data.get("positions", [])
                if isinstance(item, dict)
            ],
            closed_positions=[
                Position.from_dict(item)
                for item in data.get("closed_positions", [])
                if isinstance(item, dict)
            ],
            updated_at=data.get("updated_at"),
        )

    def open_positions(self) -> list[Position]:
        return [position for position in self.positions if position.status == "open"]

    def equity(self) -> float:
        return self.cash + sum(position.market_value for position in self.open_positions())

    def exposure(self) -> float:
        return sum(position.stake for position in self.open_positions())

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_bankroll": round(self.initial_bankroll, 2),
            "cash": round(self.cash, 2),
            "positions": [position.to_dict() for position in self.open_positions()],
            "closed_positions": [position.to_dict() for position in self.closed_positions],
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class Order:
    ticker: str
    condition_id: str
    question: str
    side: TradeSide
    price: float
    stake: float
    shares: float
    estimated_probability: float
    edge: float
    confidence: float
    thesis: str
    evidence_quality_score: float
    counter_case: tuple[str, ...] = ()


@dataclass(frozen=True)
class Exit:
    ticker: str
    condition_id: str
    side: TradeSide
    entry_price: float
    exit_price: float
    stake: float
    pnl: float
    return_pct: float
    reason: str


@dataclass(frozen=True)
class Rejection:
    ticker: str
    condition_id: Optional[str]
    reason: str
    detail: str


@dataclass(frozen=True)
class CandidateTrace:
    ticker: str
    condition_id: Optional[str]
    question: Optional[str]
    action: str
    reason: str
    detail: str
    side: Optional[TradeSide] = None
    quote: Optional[float] = None
    estimated_probability: Optional[float] = None
    edge: Optional[float] = None
    confidence: Optional[float] = None
    evidence_quality_score: Optional[float] = None
    stake: Optional[float] = None
    counter_case: tuple[str, ...] = ()
    buzz_score: Optional[float] = None
    sentiment_score: Optional[float] = None
    trend: Optional[str] = None
    market_type: Optional[str] = None
    liquidity: Optional[float] = None
    volume_24h: Optional[float] = None
    market_trade_count: Optional[int] = None
    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    end_date: Optional[str] = None


@dataclass
class RunResult:
    orders: list[Order]
    exits: list[Exit]
    rejections: list[Rejection]
    considered_markets: list[CandidateTrace]
    portfolio: Portfolio
    decision_explainer: "DecisionExplainer"

    def rejection_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rejection in self.rejections:
            counts[rejection.reason] = counts.get(rejection.reason, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


class PaperTrader:
    """Converts Adanos Polymarket API responses into simulated trades."""

    def __init__(self, config: Optional[StrategyConfig] = None) -> None:
        self.config = config or StrategyConfig()
        self.market_resolver = MarketResolver()
        self.quote_adapter = QuoteAdapter()

    def run(
        self,
        trending: Iterable[dict[str, Any]],
        details: Iterable[dict[str, Any]],
        portfolio: Portfolio,
        now: Optional[datetime] = None,
    ) -> RunResult:
        now = now or utc_now()
        stocks = [StockSignal.from_api(item) for item in trending]
        details_by_ticker, data_quality_rejections, data_quality_traces = self._details_with_rejections(details, now)
        exits = self.mark_to_market(portfolio, details_by_ticker, now)
        orders, rejections, considered_markets = self.build_orders(stocks, details_by_ticker, portfolio, now)
        rejections = data_quality_rejections + rejections
        considered_markets = data_quality_traces + considered_markets
        for order in orders:
            self.apply_order(portfolio, order, now)
        portfolio.updated_at = isoformat(now)
        return RunResult(
            orders=orders,
            exits=exits,
            rejections=rejections,
            considered_markets=considered_markets,
            portfolio=portfolio,
            decision_explainer=build_decision_explainer(
                orders=orders,
                exits=exits,
                rejections=rejections,
                portfolio=portfolio,
            ),
        )

    def mark_to_market(
        self,
        portfolio: Portfolio,
        details_by_ticker: dict[str, list[MarketSignal]],
        now: datetime,
    ) -> list[Exit]:
        markets_by_condition = {
            market.condition_id: market
            for markets in details_by_ticker.values()
            for market in markets
        }
        exits: list[Exit] = []
        remaining: list[Position] = []

        for position in portfolio.open_positions():
            market = markets_by_condition.get(position.condition_id)
            quote = market.quote_for(position.side) if market else None
            if quote is not None:
                position.current_price = quote

            reason = None
            if position.return_pct <= self.config.stop_loss_pct:
                reason = "stop_loss"
            elif position.return_pct >= self.config.take_profit_pct:
                reason = "take_profit"

            if reason is None:
                remaining.append(position)
                continue

            proceeds = position.market_value
            pnl = proceeds - position.stake
            portfolio.cash += proceeds
            position.status = "closed"
            position.closed_at = isoformat(now)
            position.exit_reason = reason
            position.realized_pnl = pnl
            portfolio.closed_positions.append(position)
            exits.append(
                Exit(
                    ticker=position.ticker,
                    condition_id=position.condition_id,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=position.current_price,
                    stake=position.stake,
                    pnl=pnl,
                    return_pct=position.return_pct,
                    reason=reason,
                )
            )

        portfolio.positions = remaining
        return exits

    def build_orders(
        self,
        stocks: Iterable[StockSignal],
        details_by_ticker: dict[str, list[MarketSignal]],
        portfolio: Portfolio,
        now: datetime,
    ) -> tuple[list[Order], list[Rejection], list[CandidateTrace]]:
        orders: list[Order] = []
        rejections: list[Rejection] = []
        traces: list[CandidateTrace] = []
        open_keys = {position.key for position in portfolio.open_positions()}
        open_tickers = {position.ticker for position in portfolio.open_positions()}
        remaining_slots = max(0, self.config.max_positions - len(open_keys))
        available_cash = portfolio.cash

        for stock in sorted(stocks, key=lambda item: (-item.buzz_score, item.ticker)):
            if len(orders) >= remaining_slots:
                rejection = Rejection(stock.ticker, None, "max_positions_reached", "no free portfolio slot")
                rejections.append(rejection)
                traces.extend(self._stock_or_market_traces(stock, details_by_ticker.get(stock.ticker, []), rejection))
                continue

            stock_rejection = self._reject_stock(stock)
            if stock_rejection is not None:
                rejections.append(stock_rejection)
                traces.extend(
                    self._stock_or_market_traces(stock, details_by_ticker.get(stock.ticker, []), stock_rejection)
                )
                continue

            if stock.ticker in open_tickers:
                rejection = Rejection(stock.ticker, None, "already_open", "ticker already open")
                rejections.append(rejection)
                traces.extend(self._stock_or_market_traces(stock, details_by_ticker.get(stock.ticker, []), rejection))
                continue

            markets = sorted(
                details_by_ticker.get(stock.ticker, []),
                key=lambda market: (-market.trade_count, -market.volume_24h, -market.liquidity),
            )
            if not markets:
                rejection = Rejection(stock.ticker, None, "missing_markets", "no top_mentions")
                rejections.append(rejection)
                traces.append(self._stock_trace(stock, rejection))
                continue

            for market in markets:
                order, rejection = self._build_order(stock, market, portfolio, open_keys, now, available_cash)
                if order is not None:
                    orders.append(order)
                    available_cash -= order.stake
                    traces.append(self._order_trace(stock, market, order))
                    open_keys.add((order.condition_id, order.side))
                    open_tickers.add(order.ticker)
                    break
                if rejection is not None:
                    rejections.append(rejection)
                    traces.append(self._rejection_trace(stock, market, rejection))

        return orders, rejections, traces

    def apply_order(self, portfolio: Portfolio, order: Order, now: datetime) -> Position:
        stake = min(order.stake, portfolio.cash)
        position = Position(
            ticker=order.ticker,
            condition_id=order.condition_id,
            question=order.question,
            side=order.side,
            shares=stake / order.price,
            entry_price=order.price,
            current_price=order.price,
            stake=stake,
            opened_at=isoformat(now),
            thesis=order.thesis,
            confidence=order.confidence,
            edge=order.edge,
            evidence_quality_score=order.evidence_quality_score,
            counter_case=order.counter_case,
        )
        portfolio.cash -= stake
        portfolio.positions.append(position)
        return position

    def _reject_stock(self, stock: StockSignal) -> Optional[Rejection]:
        if not stock.ticker:
            return Rejection("", None, "invalid_ticker", "missing ticker")
        if stock.sentiment_score is None:
            return Rejection(stock.ticker, None, "missing_sentiment", "no directional sentiment")
        if abs(stock.sentiment_score) < self.config.min_abs_sentiment:
            return Rejection(stock.ticker, None, "weak_sentiment", f"sentiment={stock.sentiment_score:.3f}")
        if stock.buzz_score < self.config.min_buzz_score:
            return Rejection(stock.ticker, None, "low_buzz", f"buzz={stock.buzz_score:.1f}")
        if stock.trade_count < self.config.min_stock_trade_count:
            return Rejection(stock.ticker, None, "low_stock_flow", f"trades={stock.trade_count}")
        if stock.trend == "falling":
            return Rejection(stock.ticker, None, "falling_flow", "trend is falling")
        if stock.trend == "stable" and not self.config.allow_stable_trend:
            return Rejection(stock.ticker, None, "stable_flow", "stable disabled")
        return None

    def _build_order(
        self,
        stock: StockSignal,
        market: MarketSignal,
        portfolio: Portfolio,
        open_keys: set[tuple[str, TradeSide]],
        now: datetime,
        available_cash: float,
    ) -> tuple[Optional[Order], Optional[Rejection]]:
        desired_direction = 1 if (stock.sentiment_score or 0) > 0 else -1
        yes_direction = derive_yes_direction(market.market_type, market.question, stock.ticker)
        if yes_direction is None:
            return None, Rejection(stock.ticker, market.condition_id, "unknown_market_direction", market.question)

        side: TradeSide = "YES" if yes_direction == desired_direction else "NO"
        if (market.condition_id, side) in open_keys:
            return None, Rejection(stock.ticker, market.condition_id, "already_open", "same market side")
        limit_rejection = self._reentry_limit_rejection(stock.ticker, side, portfolio, market.condition_id, now)
        if limit_rejection is not None:
            return None, limit_rejection

        quote = market.quote_for(side)
        if quote is None:
            return None, Rejection(stock.ticker, market.condition_id, "missing_quote", side)
        quote_result, quote_issue = self.quote_adapter.quote(
            market,
            side,
            require_token_id=self.config.require_clob_token_ids,
        )
        if quote_issue is not None:
            return None, Rejection(stock.ticker, market.condition_id, quote_issue.reason, quote_issue.detail)
        if quote_result is None:
            return None, Rejection(stock.ticker, market.condition_id, "missing_quote", side)
        quote = quote_result.reference_price
        if quote < self.config.min_price or quote > self.config.max_price:
            return None, Rejection(stock.ticker, market.condition_id, "price_out_of_range", f"{quote:.3f}")
        if not market.active:
            return None, Rejection(stock.ticker, market.condition_id, "inactive_market", "inactive")
        if market.trade_count < self.config.min_market_trade_count:
            return None, Rejection(stock.ticker, market.condition_id, "low_market_flow", str(market.trade_count))
        if market.liquidity < self.config.min_liquidity:
            return None, Rejection(stock.ticker, market.condition_id, "low_liquidity", f"{market.liquidity:.2f}")

        probability = self._estimate_probability(stock, market, desired_direction)
        edge = probability - quote
        evidence_quality_score = self._evidence_quality_score(stock, market)
        if evidence_quality_score < self.config.min_evidence_quality_score:
            return None, Rejection(
                stock.ticker,
                market.condition_id,
                "low_evidence_quality",
                f"evidence={evidence_quality_score:.3f}",
            )
        if edge < self.config.min_edge:
            return None, Rejection(stock.ticker, market.condition_id, "low_edge", f"{edge:.3f}")

        stake = self._size_stake(quote, probability, portfolio, available_cash)
        if stake < self.config.min_stake:
            return None, Rejection(stock.ticker, market.condition_id, "stake_too_small", f"{stake:.2f}")

        counter_case = self._counter_case(
            stock=stock,
            market=market,
            side=side,
            quote=quote,
            evidence_quality_score=evidence_quality_score,
        )
        confidence = self._confidence(stock, market, edge, evidence_quality_score)
        thesis = (
            f"{stock.ticker} {stock.trend or 'unknown'} flow, "
            f"buzz {stock.buzz_score:.1f}, sentiment {stock.sentiment_score:+.3f}; "
            f"paper {side} at {quote:.3f}, model p={probability:.3f}, edge={edge:.3f}, "
            f"evidence={evidence_quality_score:.3f}"
        )
        return (
            Order(
                ticker=stock.ticker,
                condition_id=market.condition_id,
                question=market.question,
                side=side,
                price=quote,
                stake=stake,
                shares=stake / quote,
                estimated_probability=probability,
                edge=edge,
                confidence=confidence,
                thesis=thesis,
                evidence_quality_score=evidence_quality_score,
                counter_case=counter_case,
            ),
            None,
        )

    def _reentry_limit_rejection(
        self,
        ticker: str,
        side: TradeSide,
        portfolio: Portfolio,
        condition_id: str,
        now: datetime,
    ) -> Optional[Rejection]:
        same_day_stop_losses = self._same_day_stop_loss_count(ticker, side, portfolio, now)
        if same_day_stop_losses >= self.config.max_stop_losses_per_day:
            return Rejection(
                ticker,
                condition_id,
                "stop_loss_limit_reached",
                f"{same_day_stop_losses} stop-loss exit(s) today",
            )

        if self.config.take_profit_cooldown_minutes <= 0:
            return None

        last_take_profit = self._last_exit(ticker, side, "take_profit", portfolio)
        if last_take_profit is None:
            return None

        closed_at = parse_isoformat(last_take_profit.closed_at)
        if closed_at is None:
            return None

        cooldown_until = closed_at + timedelta(minutes=self.config.take_profit_cooldown_minutes)
        if now >= cooldown_until:
            return None

        remaining_minutes = max(1, int((cooldown_until - now).total_seconds() // 60))
        return Rejection(
            ticker,
            condition_id,
            "take_profit_cooldown",
            f"{remaining_minutes}m remaining after take-profit",
        )

    def _same_day_stop_loss_count(
        self,
        ticker: str,
        side: TradeSide,
        portfolio: Portfolio,
        now: datetime,
    ) -> int:
        count = 0
        for position in portfolio.closed_positions:
            if position.ticker != ticker or position.side != side or position.exit_reason != "stop_loss":
                continue
            closed_at = parse_isoformat(position.closed_at)
            if closed_at is not None and closed_at.date() == now.date():
                count += 1
        return count

    def _last_exit(
        self,
        ticker: str,
        side: TradeSide,
        reason: str,
        portfolio: Portfolio,
    ) -> Optional[Position]:
        matches = [
            position
            for position in portfolio.closed_positions
            if position.ticker == ticker and position.side == side and position.exit_reason == reason
        ]
        if not matches:
            return None
        return max(matches, key=lambda position: position.closed_at or "")

    def _estimate_probability(self, stock: StockSignal, market: MarketSignal, direction: int) -> float:
        stock_signal = abs(stock.sentiment_score or 0.0)
        market_alignment = 0.0
        if market.sentiment_score is not None:
            market_alignment = max(0.0, direction * market.sentiment_score)
        signal_strength = clamp((0.70 * stock_signal) + (0.30 * market_alignment), 0.0, 1.0)
        trend_bonus = 0.025 if stock.trend == "rising" else 0.0
        heat_bonus = clamp((stock.buzz_score - 50.0) / 1000.0, -0.025, 0.05)
        liquidity_bonus = clamp(market.liquidity / 100_000.0, 0.0, 1.0) * 0.015
        flow_bonus = clamp(market.trade_count / 250.0, 0.0, 1.0) * 0.015
        return clamp(0.50 + (signal_strength * 0.25) + trend_bonus + heat_bonus + liquidity_bonus + flow_bonus, 0.01, 0.99)

    def _size_stake(
        self,
        price: float,
        probability: float,
        portfolio: Portfolio,
        available_cash: Optional[float] = None,
    ) -> float:
        if price >= 1.0 or probability <= price:
            return 0.0
        kelly = (probability - price) / (1.0 - price)
        bankroll = max(portfolio.equity(), 0.0)
        cash_budget = portfolio.cash if available_cash is None else max(available_cash, 0.0)
        risk_budget = min(self.config.max_stake, bankroll * self.config.max_position_pct, cash_budget)
        return round(min(bankroll * max(0.0, kelly) * self.config.kelly_fraction, risk_budget), 2)

    def _evidence_quality_score(self, stock: StockSignal, market: MarketSignal) -> float:
        stock_sentiment = clamp(abs(stock.sentiment_score or 0.0), 0.0, 1.0)
        buzz = clamp(stock.buzz_score / 100.0, 0.0, 1.0)
        stock_flow = clamp(stock.trade_count / 100.0, 0.0, 1.0)
        market_flow = clamp(market.trade_count / 25.0, 0.0, 1.0)
        liquidity = clamp(market.liquidity / 50_000.0, 0.0, 1.0)
        trend = {"rising": 1.0, "stable": 0.65, "falling": 0.2}.get(stock.trend or "", 0.5)
        alignment = 0.5
        if market.sentiment_score is not None and stock.sentiment_score is not None:
            stock_sign = 1 if stock.sentiment_score > 0 else -1
            market_sign = 1 if market.sentiment_score > 0 else -1
            market_strength = clamp(abs(market.sentiment_score), 0.0, 1.0)
            alignment = 0.4 + (0.6 * market_strength if stock_sign == market_sign else 0.2 * (1.0 - market_strength))
            alignment = clamp(alignment, 0.0, 1.0)

        return round(
            clamp(
                (stock_sentiment * 0.18)
                + (buzz * 0.16)
                + (stock_flow * 0.14)
                + (market_flow * 0.16)
                + (liquidity * 0.18)
                + (alignment * 0.12)
                + (trend * 0.06),
                0.0,
                1.0,
            ),
            3,
        )

    def _counter_case(
        self,
        *,
        stock: StockSignal,
        market: MarketSignal,
        side: TradeSide,
        quote: float,
        evidence_quality_score: float,
    ) -> tuple[str, ...]:
        notes: list[str] = []
        if abs(stock.sentiment_score or 0.0) < 0.25:
            notes.append("Ticker sentiment is only moderately directional.")
        if market.sentiment_score is None:
            notes.append("Market-level sentiment confirmation is missing.")
        elif stock.sentiment_score is not None and (stock.sentiment_score * market.sentiment_score) <= 0:
            notes.append("Market-level sentiment does not confirm the stock signal.")
        elif abs(market.sentiment_score) < 0.25:
            notes.append("Market-level sentiment confirmation is weak.")
        if market.trade_count < max(self.config.min_market_trade_count * 10, 10):
            notes.append("Contract trade flow is still fairly thin.")
        if market.liquidity < max(self.config.min_liquidity * 5, 10_000.0):
            notes.append("Liquidity is modest, so pricing can move noisily.")
        if quote >= 0.65:
            notes.append("Entry price is already crowded and leaves less upside.")
        elif quote <= 0.12:
            notes.append("Cheap contracts can stay cheap even when the thesis is right.")
        if stock.trend != "rising":
            notes.append("Social flow is not clearly rising, so follow-through may fade.")
        if evidence_quality_score < 0.60:
            notes.append("Evidence quality is only medium, so conviction should stay modest.")
        if market.market_type == "other":
            notes.append("Question wording may not map cleanly to the sentiment signal.")
        if not notes:
            notes.append("Polymarket pricing can move faster than sentiment data refreshes.")
            notes.append(f"{side} relies on the market framing staying directionally aligned.")
        return tuple(notes[:3])

    def _confidence(
        self,
        stock: StockSignal,
        market: MarketSignal,
        edge: float,
        evidence_quality_score: float,
    ) -> float:
        return round(
            clamp(
                (min(abs(stock.sentiment_score or 0.0), 1.0) * 0.25)
                + (clamp(stock.buzz_score / 100.0, 0.0, 1.0) * 0.25)
                + (clamp(market.liquidity / 50_000.0, 0.0, 1.0) * 0.15)
                + (clamp(market.trade_count / 100.0, 0.0, 1.0) * 0.10)
                + (clamp(edge / 0.10, 0.0, 1.0) * 0.10)
                + (evidence_quality_score * 0.15),
                0.0,
                1.0,
            ),
            3,
        )

    @staticmethod
    def _details_by_ticker(details: Iterable[dict[str, Any]]) -> dict[str, list[MarketSignal]]:
        return PaperTrader()._details_with_rejections(details, utc_now())[0]

    def _details_with_rejections(
        self,
        details: Iterable[dict[str, Any]],
        now: datetime,
    ) -> tuple[dict[str, list[MarketSignal]], list[Rejection], list[CandidateTrace]]:
        result: dict[str, list[MarketSignal]] = {}
        rejections: list[Rejection] = []
        traces: list[CandidateTrace] = []
        for detail in details:
            ticker = str(detail.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            result[ticker] = []
            for item in detail.get("top_mentions") or []:
                if not isinstance(item, dict):
                    rejections.append(
                        Rejection(ticker, None, "invalid_market_payload", "top_mentions item is not an object")
                    )
                    traces.append(
                        CandidateTrace(
                            ticker=ticker,
                            condition_id=None,
                            question=None,
                            action="skipped",
                            reason="invalid_market_payload",
                            detail="top_mentions item is not an object",
                        )
                    )
                    continue
                market, issue = self.market_resolver.resolve(
                    ticker,
                    item,
                    now=now,
                    require_token_ids=self.config.require_clob_token_ids,
                )
                if issue is not None:
                    rejections.append(Rejection(issue.ticker, issue.condition_id, issue.reason, issue.detail))
                    traces.append(
                        CandidateTrace(
                            ticker=issue.ticker,
                            condition_id=issue.condition_id,
                            question=str(item.get("question") or "").strip() or None,
                            action="skipped",
                            reason=issue.reason,
                            detail=issue.detail,
                            market_type=str(item.get("market_type") or "") or None,
                            liquidity=as_float(item.get("liquidity")),
                            volume_24h=as_float(item.get("volume_24h")),
                            market_trade_count=as_int(item.get("trade_count")),
                            yes_price=as_float(item.get("yes_price")) if item.get("yes_price") is not None else None,
                            no_price=as_float(item.get("no_price")) if item.get("no_price") is not None else None,
                            end_date=item.get("end_date") or item.get("endDate"),
                        )
                    )
                    continue
                if market is not None:
                    result[ticker].append(MarketSignal.from_normalized(market))
        return result, rejections, traces

    @staticmethod
    def _stock_trace(stock: StockSignal, rejection: Rejection) -> CandidateTrace:
        return CandidateTrace(
            ticker=stock.ticker,
            condition_id=rejection.condition_id,
            question=None,
            action="skipped",
            reason=rejection.reason,
            detail=rejection.detail,
            buzz_score=stock.buzz_score,
            sentiment_score=stock.sentiment_score,
            trend=stock.trend,
        )

    def _stock_or_market_traces(
        self,
        stock: StockSignal,
        markets: list[MarketSignal],
        rejection: Rejection,
    ) -> list[CandidateTrace]:
        if not markets:
            return [self._stock_trace(stock, rejection)]
        return [
            self._rejection_trace(
                stock,
                market,
                Rejection(stock.ticker, market.condition_id, rejection.reason, rejection.detail),
            )
            for market in markets
        ]

    def _rejection_trace(self, stock: StockSignal, market: MarketSignal, rejection: Rejection) -> CandidateTrace:
        desired_direction = 1 if (stock.sentiment_score or 0.0) > 0 else -1
        yes_direction = derive_yes_direction(market.market_type, market.question, stock.ticker)
        if yes_direction is None:
            side: TradeSide = "YES" if desired_direction > 0 else "NO"
        else:
            side = "YES" if yes_direction == desired_direction else "NO"
        quote = market.quote_for(side) or market.quote_for("YES") or market.quote_for("NO") or 0.0
        evidence_quality_score = self._evidence_quality_score(stock, market)
        return CandidateTrace(
            ticker=stock.ticker,
            condition_id=market.condition_id,
            question=market.question,
            action="skipped",
            reason=rejection.reason,
            detail=rejection.detail,
            side=side,
            quote=quote if quote > 0.0 else None,
            evidence_quality_score=evidence_quality_score,
            counter_case=self._counter_case(
                stock=stock,
                market=market,
                side=side,
                quote=quote,
                evidence_quality_score=evidence_quality_score,
            ),
            buzz_score=stock.buzz_score,
            sentiment_score=stock.sentiment_score,
            trend=stock.trend,
            market_type=market.market_type,
            liquidity=market.liquidity,
            volume_24h=market.volume_24h,
            market_trade_count=market.trade_count,
            yes_price=market.yes_price,
            no_price=market.no_price,
            end_date=market.end_date,
        )

    @staticmethod
    def _order_trace(stock: StockSignal, market: MarketSignal, order: Order) -> CandidateTrace:
        return CandidateTrace(
            ticker=stock.ticker,
            condition_id=market.condition_id,
            question=market.question,
            action="opened",
            reason="passed",
            detail=order.thesis,
            side=order.side,
            quote=order.price,
            estimated_probability=order.estimated_probability,
            edge=order.edge,
            confidence=order.confidence,
            evidence_quality_score=order.evidence_quality_score,
            stake=order.stake,
            counter_case=order.counter_case,
            buzz_score=stock.buzz_score,
            sentiment_score=stock.sentiment_score,
            trend=stock.trend,
            market_type=market.market_type,
            liquidity=market.liquidity,
            volume_24h=market.volume_24h,
            market_trade_count=market.trade_count,
            yes_price=market.yes_price,
            no_price=market.no_price,
            end_date=market.end_date,
        )


def load_portfolio(path: Path, initial_bankroll: float) -> Portfolio:
    if not path.exists():
        return Portfolio.new(initial_bankroll)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return Portfolio.new(initial_bankroll)
    return Portfolio.from_dict(data, initial_bankroll)


def save_portfolio(path: Path, portfolio: Portfolio) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(portfolio.to_dict(), handle, indent=2, sort_keys=True)
        handle.write("\n")


@dataclass(frozen=True)
class DecisionExplainer:
    posture: str
    summary: str
    rationale: tuple[str, ...] = ()


def build_decision_explainer(
    *,
    orders: list[Order],
    exits: list[Exit],
    rejections: list[Rejection],
    portfolio: Portfolio,
) -> DecisionExplainer:
    counts: dict[str, int] = {}
    for rejection in rejections:
        counts[rejection.reason] = counts.get(rejection.reason, 0) + 1
    top_blockers = [
        f"{reason}={count}"
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    ]

    if orders and exits:
        posture = "rebalance"
        summary = f"Opened {len(orders)} new trade(s) and closed {len(exits)} position(s) this cycle."
    elif orders:
        posture = "adding_risk"
        summary = f"Opened {len(orders)} new trade(s) after edge and evidence cleared the thresholds."
    elif exits:
        posture = "de_risking"
        summary = f"Closed {len(exits)} position(s) and kept cash elevated at ${portfolio.cash:.2f}."
    else:
        posture = "hold"
        blocker_text = ", ".join(top_blockers) if top_blockers else "no qualifying setups"
        summary = f"No new trades; strongest blockers were {blocker_text}."

    rationale: list[str] = [
        f"Portfolio now holds {len(portfolio.open_positions())} open position(s) with ${portfolio.cash:.2f} cash and ${portfolio.exposure():.2f} exposure."
    ]
    if orders:
        rationale.append(
            "Entries cleared thresholds: "
            + ", ".join(
                f"{order.ticker} {order.side} edge {order.edge:.3f}, evidence {order.evidence_quality_score:.2f}"
                for order in orders[:3]
            )
            + "."
        )
    if exits:
        rationale.append(
            "Exits: "
            + ", ".join(
                f"{exit_.ticker} {exit_.side} {exit_.reason} {exit_.return_pct:+.1%}"
                for exit_ in exits[:3]
            )
            + "."
        )
    if top_blockers:
        rationale.append("Top blockers: " + ", ".join(top_blockers) + ".")
    open_positions = portfolio.open_positions()
    if open_positions:
        best = max(open_positions, key=lambda position: position.return_pct)
        worst = min(open_positions, key=lambda position: position.return_pct)
        rationale.append(
            f"Open-book range: best {best.ticker} {best.return_pct:+.1%}, worst {worst.ticker} {worst.return_pct:+.1%}."
        )
    return DecisionExplainer(posture=posture, summary=summary, rationale=tuple(rationale[:4]))


def format_report(run: RunResult) -> str:
    portfolio = run.portfolio
    lines = [
        "=" * 72,
        "POLYSENTIMENT TRADER",
        "=" * 72,
        f"Equity ${portfolio.equity():.2f} | Cash ${portfolio.cash:.2f} | Open {len(portfolio.open_positions())} | Exposure ${portfolio.exposure():.2f}",
        f"Considered {len(run.considered_markets)} candidates | Entries {len(run.orders)} | Exits {len(run.exits)}",
    ]

    if run.exits:
        lines.append("\nExits")
        for exit_ in run.exits:
            lines.append(
                f"  {exit_.reason:<11} {exit_.ticker:<6} {exit_.side:<3} "
                f"{exit_.entry_price:.3f}->{exit_.exit_price:.3f} "
                f"PnL ${exit_.pnl:+.2f} ({exit_.return_pct:+.1%})"
            )

    lines.append("\nNew Paper Entries")
    if run.orders:
        for order in run.orders:
            lines.append(
                f"  {order.ticker:<6} BUY {order.side:<3} "
                f"${order.stake:>6.2f} @ {order.price:.3f} "
                f"edge {order.edge:.3f} conf {order.confidence:.2f}"
            )
            lines.append(f"    {order.question[:112]}")
            lines.append(f"    {order.thesis}")
    else:
        lines.append("  none")

    counts = run.rejection_counts()
    if counts:
        top_counts = ", ".join(f"{reason}={count}" for reason, count in list(counts.items())[:8])
        lines.append("\nSkipped")
        lines.append(f"  {top_counts}")

    lines.append("\nDecision")
    lines.append(f"  {run.decision_explainer.summary}")
    for rationale in run.decision_explainer.rationale[:3]:
        lines.append(f"  {rationale}")

    return "\n".join(lines)
