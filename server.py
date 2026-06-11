"""Email on Acid MCP server.

Exposes every documented Email on Acid API v5 request as an MCP tool.
API docs: https://api.emailonacid.com/docs/

Authentication: HTTP Basic auth where the username is your API key and the
password is your (optional) account password. Credentials are resolved from
the EOA_API_KEY / EOA_ACCOUNT_PASSWORD environment variables, including
values loaded from a .env file next to this script.
"""

import base64
import functools
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent / ".env")

BASE_URL = "https://api.emailonacid.com/v5"

mcp = FastMCP("email-on-acid")


@functools.lru_cache(maxsize=1)
def _credentials() -> tuple[str, str]:
    api_key = os.environ.get("EOA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "EOA_API_KEY is not set. Copy .env.example to .env and fill in "
            "your API key."
        )
    return api_key, os.environ.get("EOA_ACCOUNT_PASSWORD", "")


def _auth_header() -> str:
    api_key, password = _credentials()
    token = base64.b64encode(f"{api_key}:{password}".encode()).decode()
    return f"Basic {token}"


def _request(
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> Any:
    headers = {
        "Authorization": _auth_header(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=120) as client:
        response = client.request(method, path, params=params, json=json_body)
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if response.status_code >= 400:
        return {"http_status": response.status_code, "error": payload}
    return payload


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@mcp.tool()
def verify_auth() -> Any:
    """Verify API credentials (GET /auth). Returns {"success": true} when the
    configured EOA_API_KEY / EOA_ACCOUNT_PASSWORD are valid."""
    return _request("GET", "/auth")


# ---------------------------------------------------------------------------
# Email client lists
# ---------------------------------------------------------------------------


@mcp.tool()
def get_available_email_clients() -> Any:
    """List all email clients available for rendering tests (GET /email/clients).
    On client-restricted plans, only eligible clients are returned. Each client
    includes id, display name, OS, category (Application/Mobile/Web), and flags
    such as rotate, image_blocking, free, and default."""
    return _request("GET", "/email/clients")


@mcp.tool()
def get_default_email_clients() -> Any:
    """Get the client IDs currently configured to run by default on new email
    tests (GET /email/clients/default)."""
    return _request("GET", "/email/clients/default")


@mcp.tool()
def set_default_email_clients(clients: list[str]) -> Any:
    """Replace the account's default client list (PUT /email/clients/default).

    Args:
        clients: Client IDs to set as defaults. Invalid IDs are dropped and
            reported back in a "warnings" array.
    """
    return _request("PUT", "/email/clients/default", json_body={"clients": clients})


# ---------------------------------------------------------------------------
# Email testing
# ---------------------------------------------------------------------------


@mcp.tool()
def create_email_test(
    subject: str,
    html: Optional[str] = None,
    url: Optional[str] = None,
    transfer_encoding: Optional[str] = None,
    charset: Optional[str] = None,
    free_test: Optional[bool] = None,
    sandbox: Optional[bool] = None,
    reference_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    clients: Optional[list[str]] = None,
    image_blocking: Optional[bool] = None,
    spam: Optional[dict[str, Any]] = None,
) -> Any:
    """Create a new email rendering test (POST /email/tests).

    Args:
        subject: Email subject line.
        html: Email HTML source. Required if url is not provided.
        url: URL pointing to the email source. Required if html is not provided.
        transfer_encoding: One of base64, quoted-printable, 7bit, 8bit (default 8bit).
        charset: Character encoding (default utf-8).
        free_test: Run with limited features.
        sandbox: Run without creating content (returns mock data).
        reference_id: Enterprise customers only.
        customer_id: Enterprise customers only.
        headers: X-Header key/value pairs (enterprise only).
        clients: Client IDs to test against; omit to use account defaults.
        image_blocking: Also capture screenshots with images blocked.
        spam: Optional spam test configuration, e.g.
            {"test_method": "eoa"|"smtp"|"seed", "smtp_info": {...},
             "from_address": "...", "key": "..."}.

    Returns the new test id, plus spam address_list / customer info when applicable.
    """
    if not html and not url:
        return {"error": "Provide either html or url."}
    body = _drop_none(
        {
            "subject": subject,
            "html": html,
            "url": url,
            "transfer_encoding": transfer_encoding,
            "charset": charset,
            "free_test": free_test,
            "sandbox": sandbox,
            "reference_id": reference_id,
            "customer_id": customer_id,
            "headers": headers,
            "clients": clients,
            "image_blocking": image_blocking,
            "spam": spam,
        }
    )
    return _request("POST", "/email/tests", json_body=body)


@mcp.tool()
def get_email_tests() -> Any:
    """List all email tests on the account (GET /email/tests). Each entry has
    id, date (UNIX timestamp), type (email-test or spam-test), and headers.
    Results are retained for 90 days."""
    return _request("GET", "/email/tests")


@mcp.tool()
def search_email_tests(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    subject: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    results: Optional[int] = None,
    page: Optional[int] = None,
) -> Any:
    """Search email tests (GET /email/tests with a query string).

    Args:
        from_date: Start of date range — UNIX timestamp, "YYYY-MM-DD HH:MM:SS",
            or relative values like "yesterday". Sent as the "from" parameter.
        to_date: End of date range (same formats). Sent as the "to" parameter.
        subject: Exact subject match, case-insensitive.
        headers: Enterprise x-header filters as key/value pairs.
        results: Results per page, 1-200 (default 50).
        page: Page number (default 1).
    """
    params: dict[str, Any] = _drop_none(
        {"from": from_date, "to": to_date, "subject": subject, "results": results, "page": page}
    )
    if headers:
        for key, value in headers.items():
            params[f"headers[{key}]"] = value
    return _request("GET", "/email/tests", params=params)


@mcp.tool()
def get_email_test_info(test_id: str) -> Any:
    """Get summary info for one email test (GET /email/tests/{test_id}):
    subject, submission timestamp, and clients grouped by status
    (completed / processing / bounced)."""
    return _request("GET", f"/email/tests/{test_id}")


@mcp.tool()
def delete_email_test(test_id: str) -> Any:
    """Delete an email test and its results (DELETE /email/tests/{test_id}).
    This cannot be undone."""
    return _request("DELETE", f"/email/tests/{test_id}")


@mcp.tool()
def get_email_test_results(test_id: str, client_id: Optional[str] = None) -> Any:
    """Get rendering results for an email test
    (GET /email/tests/{test_id}/results[/{client_id}]).

    Args:
        test_id: The email test ID.
        client_id: Optional — restrict results to a single client.

    Returns per-client display name, OS, category, screenshot URLs (default,
    no_images, horizontal), thumbnails, and status/bounce info.
    """
    path = f"/email/tests/{test_id}/results"
    if client_id:
        path += f"/{client_id}"
    return _request("GET", path)


@mcp.tool()
def reprocess_email_test_screenshots(test_id: str, clients: list[str]) -> Any:
    """Re-capture screenshots for specific clients on an existing test
    (PUT /email/tests/{test_id}/results/reprocess).

    Args:
        test_id: The email test ID.
        clients: Client IDs to reprocess.

    Returns per-client success, remaining_reprocesses count, and regional flag.
    """
    return _request(
        "PUT",
        f"/email/tests/{test_id}/results/reprocess",
        json_body={"clients": clients},
    )


@mcp.tool()
def get_email_test_content(test_id: str) -> Any:
    """Get the original HTML source submitted for a test
    (GET /email/tests/{test_id}/content)."""
    return _request("GET", f"/email/tests/{test_id}/content")


@mcp.tool()
def get_email_test_content_inline_css(test_id: str) -> Any:
    """Get the test's HTML with all stylesheets inlined
    (GET /email/tests/{test_id}/content/inlinecss)."""
    return _request("GET", f"/email/tests/{test_id}/content/inlinecss")


@mcp.tool()
def get_email_test_content_text_only(test_id: str) -> Any:
    """Get a plain-text approximation of the test's HTML
    (GET /email/tests/{test_id}/content/textonly)."""
    return _request("GET", f"/email/tests/{test_id}/content/textonly")


@mcp.tool()
def get_email_test_spam_results(test_id: str) -> Any:
    """Get spam-filter results for an email test that included a spam check
    (GET /email/tests/{test_id}/spam/results). Each entry has client,
    type (b2c/b2b), spam verdict, and details."""
    return _request("GET", f"/email/tests/{test_id}/spam/results")


@mcp.tool()
def get_email_test_spam_seedlist(test_id: str) -> Any:
    """Get the seed-list email addresses for an email test using seed-based
    spam testing (GET /email/tests/{test_id}/spam/seedlist)."""
    return _request("GET", f"/email/tests/{test_id}/spam/seedlist")


# ---------------------------------------------------------------------------
# Spam testing
# ---------------------------------------------------------------------------


@mcp.tool()
def get_spam_clients() -> Any:
    """List available spam-filter clients (GET /spam/clients). Each entry has
    client name, type (b2c/b2b), and description."""
    return _request("GET", "/spam/clients")


@mcp.tool()
def create_spam_test(
    subject: str,
    html: Optional[str] = None,
    url: Optional[str] = None,
    transfer_encoding: Optional[str] = None,
    charset: Optional[str] = None,
    sandbox: Optional[bool] = None,
    reference_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    test_method: Optional[str] = None,
    smtp_info: Optional[dict[str, Any]] = None,
    from_address: Optional[str] = None,
    key: Optional[str] = None,
) -> Any:
    """Create a standalone spam test (POST /spam/tests).

    Args:
        subject: Email subject line.
        html: Email HTML source. Required if url is not provided.
        url: URL pointing to the email source. Required if html is not provided.
        transfer_encoding: One of base64, quoted-printable, 7bit, 8bit (default 8bit).
        charset: Character encoding (default utf-8).
        sandbox: Test mode flag (default false).
        reference_id: Enterprise reference identifier.
        customer_id: Enterprise customer identifier.
        test_method: "eoa" (default), "smtp", or "seed".
        smtp_info: Required when test_method is "smtp" —
            {"host": ..., "port": ..., "secure": ..., "username": ..., "password": ...}.
        from_address: Sender email address.
        key: Seedlist key obtained from reserve_spam_seedlist (seed method).

    Returns the test id and, for seed tests, the address_list to send to.
    """
    if not html and not url:
        return {"error": "Provide either html or url."}
    body = _drop_none(
        {
            "subject": subject,
            "html": html,
            "url": url,
            "transfer_encoding": transfer_encoding,
            "charset": charset,
            "sandbox": sandbox,
            "reference_id": reference_id,
            "customer_id": customer_id,
            "test_method": test_method,
            "smtp_info": smtp_info,
            "from_address": from_address,
            "key": key,
        }
    )
    return _request("POST", "/spam/tests", json_body=body)


@mcp.tool()
def get_spam_tests() -> Any:
    """List all spam tests on the account (GET /spam/tests). Each entry has
    id, date, type, and headers."""
    return _request("GET", "/spam/tests")


@mcp.tool()
def search_spam_tests(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    subject: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    results: Optional[int] = None,
    page: Optional[int] = None,
) -> Any:
    """Search spam tests (GET /spam/tests with a query string).

    Args:
        from_date: Start of date range — UNIX timestamp, "YYYY-MM-DD HH:MM:SS",
            or relative values like "yesterday". Sent as the "from" parameter.
        to_date: End of date range (same formats). Sent as the "to" parameter.
        subject: Exact subject match, case-insensitive.
        headers: Enterprise x-header filters as key/value pairs.
        results: Results per page, 1-200 (default 50).
        page: Page number (default 1).
    """
    params: dict[str, Any] = _drop_none(
        {"from": from_date, "to": to_date, "subject": subject, "results": results, "page": page}
    )
    if headers:
        for key, value in headers.items():
            params[f"headers[{key}]"] = value
    return _request("GET", "/spam/tests", params=params)


@mcp.tool()
def get_spam_test_results(test_id: str) -> Any:
    """Get results for a spam test (GET /spam/tests/{test_id}). Each entry has
    client, type (b2b/b2c), spam verdict (1 spam, 0 neutral, -1 not spam),
    and filter details."""
    return _request("GET", f"/spam/tests/{test_id}")


@mcp.tool()
def delete_spam_test(test_id: str) -> Any:
    """Delete a spam test and its results (DELETE /spam/tests/{test_id}).
    This cannot be undone."""
    return _request("DELETE", f"/spam/tests/{test_id}")


@mcp.tool()
def get_spam_test_seedlist(test_id: str) -> Any:
    """Get the seed-list addresses associated with a spam test
    (GET /spam/tests/{test_id}/seedlist)."""
    return _request("GET", f"/spam/tests/{test_id}/seedlist")


@mcp.tool()
def reserve_spam_seedlist() -> Any:
    """Reserve a new spam seed list (GET /spam/seedlist). Returns a key (pass it
    to create_spam_test with test_method="seed") and the address_list of seed
    inboxes to send your email to."""
    return _request("GET", "/spam/seedlist")


if __name__ == "__main__":
    mcp.run()
