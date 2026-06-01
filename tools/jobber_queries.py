"""Jobber GraphQL query strings + client normalization — the single place to adjust when
the owner confirms exact schema names in GraphiQL (Layer 1, read-only).

Everything here is a QUERY (read). No mutations exist in this layer.

>>> CONFIRM IN GRAPHiQL (Developer Center -> Manage Apps -> Test in GraphiQL -> Documentation):
  - Client sub-field names below: emails { address }, phones { number },
    billingAddress { street1 street2 city province postalCode country }.
  - The `requests` connection: we use Relay-standard first/after. If the schema requires a
    sort/filter argument to order by creation, add it to REQUESTS_QUERY.
  - The clients search argument name: we use `searchTerm` (CLIENTS_SEARCH_ARG). Adjust if
    the schema names it differently (e.g. a `filter`/`searchTerm` variant).
If any name differs, fix it HERE and every tool follows automatically.
"""
from __future__ import annotations

# Argument used to search the clients connection by a free-text term. Confirm in GraphiQL.
CLIENTS_SEARCH_ARG = "searchTerm"

# Bounded client selection — one level deep only (no deep nesting; keeps query cost low).
CLIENT_FIELDS = """
  id
  firstName
  lastName
  companyName
  emails { address }
  phones { number }
  billingAddress { street1 street2 city province postalCode country }
"""

# Poll Requests with Relay cursor pagination; pull the linked Client in the same bounded query.
REQUESTS_QUERY = """
query NewRequests($first: Int!, $after: String) {
  requests(first: $first, after: $after) {
    totalCount
    pageInfo { endCursor hasNextPage }
    nodes {
      id
      title
      createdAt
      source
      client { %s }
    }
  }
}
""" % CLIENT_FIELDS

# Targeted client search for duplicate detection (by email/phone/name term).
CLIENTS_SEARCH_QUERY = """
query SearchClients($term: String!, $first: Int!) {
  clients(%s: $term, first: $first) {
    nodes { %s }
  }
}
""" % (CLIENTS_SEARCH_ARG, CLIENT_FIELDS)

# Minimal connectivity/cost probe used by jobber_auth.py --smoke (read clients scope).
SMOKE_QUERY = "query Smoke { clients(first: 1) { totalCount } }"


def format_address(addr: dict | None) -> str:
    """Join the address parts into one display string, skipping blanks."""
    addr = addr or {}
    parts = [addr.get("street1"), addr.get("street2"), addr.get("city"),
             addr.get("province"), addr.get("postalCode"), addr.get("country")]
    return ", ".join(p.strip() for p in parts if p and str(p).strip())


def normalize_client(node: dict | None) -> dict:
    """Turn a Jobber Client GraphQL node into the engine's canonical client dict."""
    if not node:
        return {}
    emails = [e.get("address", "").strip() for e in (node.get("emails") or []) if e.get("address")]
    phones = [p.get("number", "").strip() for p in (node.get("phones") or []) if p.get("number")]
    addr = node.get("billingAddress") or {}
    first = (node.get("firstName") or "").strip()
    last = (node.get("lastName") or "").strip()
    company = (node.get("companyName") or "").strip()
    name = company or " ".join(x for x in [first, last] if x)
    return {
        "id": node.get("id", ""),
        "name": name,
        "first_name": first,
        "last_name": last,
        "company_name": company,
        "emails": emails,
        "phones": phones,
        "address": addr,
        "address_str": format_address(addr),
    }
