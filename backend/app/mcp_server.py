"""Read-only MCP server (official MCP Python SDK 2.x, streamable HTTP), mounted by main.py at /mcp.

Tools: search_catalog, resolve_line_item, get_compatible_parts, check_stock, get_price.
Connect from an MCP client with the URL  https://<backend>/mcp/  (see README).
"""
from __future__ import annotations

from typing import Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .tools import get_catalog
from .tools.schemas import LineItemIn

mcp = MCPServer(name="quotedesk-catalog",
                instructions=("Read-only tools over the fictional Northbeam Industrial Supply catalog (synthetic data). "
                              "Prices come from the pricing rules of each customer tier."))


@mcp.tool(description="Search the catalog by SKU, alias or free text. Returns up to `limit` candidates with scores.")
def search_catalog(query: str, limit: int = 5) -> list[dict]:
    return [c.model_dump() for c in get_catalog().search_catalog(query, limit=min(max(limit, 1), 20))]


@mcp.tool(description="Resolve one extracted line item to the top 3 SKU candidates with a CONFIDENT/NEEDS_REVIEW status.")
def resolve_line_item(description: str, quantity: Optional[int] = None, part_number: Optional[str] = None,
                      compatible_with: Optional[str] = None, customer_id: Optional[str] = None) -> dict:
    item = LineItemIn(description=description, quantity=quantity, part_number=part_number,
                      compatible_with=compatible_with)
    return get_catalog().resolve_line_item(item, customer_id).model_dump()


@mcp.tool(description="Parts listed as compatible with an equipment model, optionally filtered by category.")
def get_compatible_parts(equipment_model: str, category: Optional[str] = None) -> list[dict]:
    return [c.model_dump() for c in get_catalog().get_compatible_parts(equipment_model, category)]


@mcp.tool(description="Stock on hand for a SKU and whether it covers the requested quantity.")
def check_stock(sku: str, qty: int = 1) -> dict:
    cat = get_catalog()
    if sku not in cat.by_sku:
        return {"error": f"unknown sku {sku}"}
    return cat.check_stock(sku, qty).model_dump()


@mcp.tool(description="Customer price for a SKU and quantity (tier discount + volume breaks). customer_id like C001.")
def get_price(sku: str, qty: int = 1, customer_id: Optional[str] = None) -> dict:
    cat = get_catalog()
    if sku not in cat.by_sku:
        return {"error": f"unknown sku {sku}"}
    return cat.get_price(sku, customer_id, max(qty, 1)).model_dump()


def mcp_asgi_app():
    """Starlette sub-app for FastAPI's app.mount('/mcp', ...). Stateless JSON mode suits scale-to-zero hosting."""
    return mcp.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
