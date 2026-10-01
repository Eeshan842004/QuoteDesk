"""Pydantic inputs/outputs for the deterministic tools (also exposed read-only over MCP)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Candidate(BaseModel):
    sku: str
    name: str
    category: str
    score: float = Field(ge=0, le=1)
    reason: str
    unit: str
    stock_qty: int


class LineItemIn(BaseModel):
    description: str
    quantity: Optional[int] = None
    unit: Optional[str] = None
    part_number: Optional[str] = None
    compatible_with: Optional[str] = None
    reference: Optional[Literal["previous_order"]] = None


class OrderLine(BaseModel):
    order_id: str
    date: str
    sku: str
    name: str
    qty: int


class ResolveResult(BaseModel):
    candidates: list[Candidate]
    status: Literal["CONFIDENT", "NEEDS_REVIEW"]
    reasons: list[str]
    expanded: list[OrderLine] = Field(default_factory=list, description="lines from a repeated past order")


class StockResult(BaseModel):
    sku: str
    stock_qty: int
    requested: int
    sufficient: bool


class PriceResult(BaseModel):
    sku: str
    customer_id: Optional[str]
    tier: Optional[str]
    qty: int
    list_price: float
    tier_discount: float
    volume_discount: float
    discount_pct: float
    unit_price: float
    line_total: float
