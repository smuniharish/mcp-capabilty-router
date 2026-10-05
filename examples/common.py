"""Demo MCP servers and helpers shared by the examples.

The servers run in process through FastMCP, so the examples need no network,
no subprocess, and no credentials.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from fastmcp import FastMCP

from mcp_capability_router import Capability, Prompt, PromptArgument, Resource, Tool

# The demo servers reject some requests on purpose; keep their logs out of the output.
logging.getLogger("fastmcp").setLevel(logging.CRITICAL)

_KINDS: dict[str, type[Capability]] = {
    "tool": Tool,
    "resource": Resource,
    "prompt": Prompt,
}


def capability_to_json(capability: Capability) -> str:
    """Serialize a capability record for a database."""
    fields: dict[str, Any] = asdict(capability)
    fields["type"] = str(capability.type)
    return json.dumps(fields, default=sorted)


def capability_from_json(document: str) -> Capability:
    """Rebuild a capability record serialized by `capability_to_json`."""
    fields: dict[str, Any] = json.loads(document)
    kind = _KINDS[fields.pop("type")]
    fields["tags"] = frozenset(fields["tags"])
    fields["depends_on"] = frozenset(fields["depends_on"])
    if kind is Prompt:
        fields["arguments"] = tuple(
            PromptArgument(**argument) for argument in fields["arguments"]
        )
    return kind(**fields)


CUSTOMERS = {
    "c-100": {"name": "Acme Corp", "email": "ops@acme.example", "plan": "enterprise"},
    "c-200": {"name": "Globex", "email": "it@globex.example", "plan": "team"},
}
INVOICES = {
    "inv-1": {"customer_id": "c-100", "amount": 1200, "status": "paid"},
    "inv-2": {"customer_id": "c-200", "amount": 300, "status": "open"},
}


def crm_server() -> FastMCP:
    """A customer-relationship server with tools, a resource, and a prompt."""
    server = FastMCP("crm")

    @server.tool(tags={"customers"}, annotations={"readOnlyHint": True})
    def search_customers(query: str) -> list[dict[str, str]]:
        """Search customers by name."""
        return [
            {"id": key, **customer}
            for key, customer in CUSTOMERS.items()
            if query.lower() in customer["name"].lower()
        ]

    @server.tool(tags={"customers"})
    def update_customer_email(customer_id: str, email: str) -> dict[str, str]:
        """Change the email address of a customer."""
        if customer_id not in CUSTOMERS:
            msg = f"unknown customer {customer_id}"
            raise ValueError(msg)
        return {"id": customer_id, "email": email}

    @server.resource(
        "crm://schema/customer",
        name="customer-schema",
        description="Fields of a customer record",
        mime_type="application/json",
    )
    def customer_schema() -> str:
        return '{"id": "string", "name": "string", "email": "string", "plan": "string"}'

    @server.prompt(description="Draft a follow-up email to a customer")
    def follow_up(customer_name: str, topic: str) -> str:
        return (
            f"Write a short, friendly follow-up email to {customer_name} about {topic}."
        )

    return server


def billing_server() -> FastMCP:
    """A billing server whose refund tool is marked destructive."""
    server = FastMCP("billing")

    @server.tool(tags={"invoices"}, annotations={"readOnlyHint": True})
    def list_invoices(customer_id: str) -> list[dict[str, object]]:
        """List the invoices of a customer."""
        return [
            {"id": key, **invoice}
            for key, invoice in INVOICES.items()
            if invoice["customer_id"] == customer_id
        ]

    @server.tool(tags={"invoices", "refunds"}, annotations={"destructiveHint": True})
    def issue_refund(invoice_id: str, amount: int) -> dict[str, object]:
        """Refund part or all of a paid invoice."""
        invoice = INVOICES.get(invoice_id)
        if invoice is None or invoice["status"] != "paid":
            msg = f"invoice {invoice_id} cannot be refunded"
            raise ValueError(msg)
        return {"invoice_id": invoice_id, "refunded": amount}

    @server.resource(
        "billing://policies/refunds",
        name="refund-policy",
        description="When refunds are allowed",
        mime_type="text/markdown",
    )
    def refund_policy() -> str:
        return "# Refunds\nPaid invoices can be refunded within 30 days."

    @server.prompt(description="Explain an invoice to a customer in plain words")
    def explain_invoice(invoice_id: str) -> str:
        return f"Explain invoice {invoice_id} in plain words."

    return server


def docs_server() -> FastMCP:
    """A documentation server with a search tool and two guides."""
    server = FastMCP("docs")

    @server.tool(annotations={"readOnlyHint": True})
    def search_docs(query: str) -> list[str]:
        """Search the product documentation."""
        return [f"Getting started: {query}"]

    @server.resource(
        "docs://guides/getting-started",
        name="getting-started",
        description="Install the product and make a first request",
        mime_type="text/markdown",
    )
    def getting_started() -> str:
        return "# Getting started\nInstall, configure, and call the API."

    @server.resource(
        "docs://guides/billing",
        name="billing-guide",
        description="How invoices and refunds work",
        mime_type="text/markdown",
    )
    def billing_guide() -> str:
        return "# Billing\nInvoices are issued monthly."

    return server
