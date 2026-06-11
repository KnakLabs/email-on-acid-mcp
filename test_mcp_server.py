"""
Test script for server.py - calls tools through the MCP protocol.
Spawns the MCP server as a subprocess over stdio (no separate server start needed).
Credentials are resolved by the server itself (.env file).
Run: .venv/bin/python test_mcp_server.py
"""

import asyncio
import json
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

passed = 0
failed = 0
skipped = 0

# Track created tests for cleanup
created_tests = {
    'email_tests': [],   # list of email test IDs
    'spam_tests': []     # list of spam test IDs
}


async def call_tool(session, tool_name, arguments=None):
    """Call an MCP tool and return the parsed result."""
    if arguments is None:
        arguments = {}

    result = await session.call_tool(tool_name, arguments)

    # Prefer structured content - it preserves the tool's exact return shape
    # (FastMCP wraps non-object returns as {"result": ...})
    if result and result.structuredContent is not None:
        sc = result.structuredContent
        if isinstance(sc, dict) and set(sc.keys()) == {'result'}:
            return sc['result']
        return sc

    if result and result.content:
        # Fallback: FastMCP serializes a list return as one content block per item
        parsed = []
        for block in result.content:
            try:
                parsed.append(json.loads(block.text))
            except json.JSONDecodeError:
                parsed.append(block.text)
        return parsed[0] if len(parsed) == 1 else parsed

    return None


def is_api_error(result):
    """Check whether a tool result is an Email on Acid API error.

    The server returns {"http_status": ..., "error": {...}} for HTTP >= 400
    and {"error": "..."} for client-side validation problems.
    """
    return isinstance(result, dict) and ('http_status' in result or
                                         set(result.keys()) == {'error'})


async def test(session, name, tool_name, arguments=None):
    """Run a single MCP tool test and track the result."""
    global passed, failed
    try:
        result = await call_tool(session, tool_name, arguments)

        if is_api_error(result):
            print(f"  [FAIL] {name}")
            print(f"         {result}")
            failed += 1
            return None

        print(f"  [PASS] {name}")
        passed += 1
        return result

    except Exception as e:
        print(f"  [FAIL] {name} - {e}")
        failed += 1
        return None


async def test_optional(session, name, tool_name, arguments=None, reason=""):
    """Run a test where an API error is expected for some accounts/tests
    (e.g. spam results on a test with no spam component). API errors are
    reported as SKIP instead of FAIL."""
    global passed, skipped
    try:
        result = await call_tool(session, tool_name, arguments)

        if is_api_error(result):
            skip(name, reason or f"API returned: {result.get('error')}")
            return None

        print(f"  [PASS] {name}")
        passed += 1
        return result

    except Exception as e:
        skip(name, str(e))
        return None


def skip(name, reason=""):
    """Mark a test as skipped."""
    global skipped
    msg = f"  [SKIP] {name}"
    if reason:
        msg += f" - {reason}"
    print(msg)
    skipped += 1


def print_summary():
    """Print final test results."""
    total = passed + failed + skipped
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {skipped} skipped (total: {total})")
    print(f"{'=' * 60}")


def first_test_of_type(tests, test_type):
    """Find the first test of a given type in a get_*_tests result list."""
    if not isinstance(tests, list):
        return None
    for t in tests:
        if t.get('type') == test_type:
            return t
    return None


# ============================================================================
# Read-Only Tests
# ============================================================================

async def run_readonly_tests(session):
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("MCP SERVER - READ-ONLY TESTS")
    print("=" * 60)

    # --- List available tools ---
    print("\n--- Server Connection ---")
    try:
        tools = await session.list_tools()
        print(f"  [PASS] list_tools() - {len(tools.tools)} tools available")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] list_tools() - {e}")
        failed += 1
        print("\nCannot connect to MCP server. Exiting.")
        print_summary()
        return

    # --- Authentication ---
    print("\n--- Authentication ---")
    await test(session, "verify_auth", "verify_auth")

    # --- Email client lists ---
    print("\n--- Email Clients ---")
    clients = await test(session, "get_available_email_clients", "get_available_email_clients")
    if clients and clients.get('clients'):
        print(f"         Found {len(clients['clients'])} available clients")

    defaults = await test(session, "get_default_email_clients", "get_default_email_clients")
    if defaults and defaults.get('clients'):
        print(f"         Found {len(defaults['clients'])} default clients")

    # --- Email tests ---
    print("\n--- Email Tests ---")
    email_tests = await test(session, "get_email_tests", "get_email_tests")
    if isinstance(email_tests, list):
        print(f"         Found {len(email_tests)} tests on account")

    await test(session, "search_email_tests(results=5)",
               "search_email_tests", {"results": 5, "page": 1})

    # --- Email test detail lookups using auto-discovered IDs ---
    print("\n--- Email Test Detail Tests (auto-discovered) ---")
    email_test = first_test_of_type(email_tests, 'email-test')
    if email_test:
        tid = email_test['id']
        print(f"  Using email test ID: {tid}")

        await test(session, f"get_email_test_info({tid})",
                   "get_email_test_info", {"test_id": tid})

        results = await test(session, f"get_email_test_results({tid})",
                             "get_email_test_results", {"test_id": tid})

        # Per-client results using the first client in the full results
        client_id = None
        if isinstance(results, dict) and results:
            client_id = next(iter(results), None)
        if client_id:
            await test(session, f"get_email_test_results({tid}, {client_id})",
                       "get_email_test_results", {"test_id": tid, "client_id": client_id})
        else:
            skip("get_email_test_results(client_id)", "no client found in results")

        await test(session, f"get_email_test_content({tid})",
                   "get_email_test_content", {"test_id": tid})
        await test(session, f"get_email_test_content_inline_css({tid})",
                   "get_email_test_content_inline_css", {"test_id": tid})
        await test(session, f"get_email_test_content_text_only({tid})",
                   "get_email_test_content_text_only", {"test_id": tid})

        # Only applicable if the test was created with a spam component
        await test_optional(session, f"get_email_test_spam_results({tid})",
                            "get_email_test_spam_results", {"test_id": tid},
                            reason="test has no spam component")
        await test_optional(session, f"get_email_test_spam_seedlist({tid})",
                            "get_email_test_spam_seedlist", {"test_id": tid},
                            reason="test has no seed-based spam component")
    else:
        for t in ("get_email_test_info", "get_email_test_results",
                  "get_email_test_content", "get_email_test_content_inline_css",
                  "get_email_test_content_text_only", "get_email_test_spam_results",
                  "get_email_test_spam_seedlist"):
            skip(t, "no email tests found on account")

    # --- Spam tests ---
    print("\n--- Spam Tests ---")
    spam_clients = await test(session, "get_spam_clients", "get_spam_clients")
    if isinstance(spam_clients, list):
        print(f"         Found {len(spam_clients)} spam clients")

    spam_tests = await test(session, "get_spam_tests", "get_spam_tests")
    if isinstance(spam_tests, list):
        print(f"         Found {len(spam_tests)} tests on account")

    await test(session, "search_spam_tests(results=5)",
               "search_spam_tests", {"results": 5, "page": 1})

    # --- Spam test detail lookups using auto-discovered IDs ---
    print("\n--- Spam Test Detail Tests (auto-discovered) ---")
    spam_test = first_test_of_type(spam_tests, 'spam-test')
    if spam_test:
        tid = spam_test['id']
        print(f"  Using spam test ID: {tid}")

        await test(session, f"get_spam_test_results({tid})",
                   "get_spam_test_results", {"test_id": tid})
        await test_optional(session, f"get_spam_test_seedlist({tid})",
                            "get_spam_test_seedlist", {"test_id": tid},
                            reason="test is not seed-based")
    else:
        skip("get_spam_test_results", "no spam tests found on account")
        skip("get_spam_test_seedlist", "no spam tests found on account")

    print_summary()


# ============================================================================
# Write-Only Tests (create, update, delete)
# ============================================================================

TEST_HTML = """<html><body><h1>MCPTEST</h1><p>Test email from the Email on Acid MCP test suite.</p></body></html>"""


async def run_write_tests(session):
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("WRITE OPERATIONS TESTS (via MCP)")
    print("=" * 60)
    print("\nThese tests will CREATE and UPDATE tests on Email on Acid.")
    print("Created tests use sandbox mode by default (no test credits consumed)")
    print("and subjects are prefixed with 'MCPTEST_' for easy identification.\n")

    # --- Set Default Clients (no-op: re-set the current defaults) ---
    print("--- Set Default Clients ---")
    defaults = await call_tool(session, "get_default_email_clients")
    if defaults and defaults.get('clients'):
        await test(session, f"set_default_email_clients({len(defaults['clients'])} current defaults)",
                   "set_default_email_clients", {"clients": defaults['clients']})
    else:
        skip("set_default_email_clients", "no current defaults to safely re-set")

    # --- Create Email Test (sandbox) ---
    print("\n--- Create Email Test (sandbox) ---")
    created_email = await test(session, "create_email_test('MCPTEST_Email', sandbox=True)",
                               "create_email_test",
                               {"subject": "MCPTEST_Email",
                                "html": TEST_HTML,
                                "sandbox": True})
    if created_email and created_email.get('id'):
        print(f"         Created sandbox email test ID: {created_email['id']}")

    # --- Reserve Spam Seed List (key is reused by the spam-component tests below) ---
    print("\n--- Reserve Spam Seed List ---")
    seedlist = await test_optional(session, "reserve_spam_seedlist", "reserve_spam_seedlist",
                                   reason="seed list testing may not be enabled on this plan")
    seed_key = seedlist.get('key') if isinstance(seedlist, dict) else None
    if seed_key:
        print(f"         Reserved seedlist key: {seed_key} "
              f"({len(seedlist.get('address_list', []))} addresses)")

    # --- Create Email Test (real, consumes a credit) ---
    # Includes a seed-based spam component so the email-test spam tools can be
    # exercised (sandbox email tests return a fake "sandbox" ID that cannot be
    # queried, so a real test is the only way to cover these).
    print("\n--- Create Email Test (real, with spam component) ---")
    print("  WARNING: This will create a real rendering test and consume a test credit.")
    confirm = input("  Proceed? (y/n): ").strip().lower()
    if confirm in ('y', 'yes'):
        args = {"subject": "MCPTEST_Email_Real", "html": TEST_HTML}
        if seed_key:
            args["spam"] = {"test_method": "seed", "key": seed_key}
        real_email = await test(session, "create_email_test('MCPTEST_Email_Real', spam=seed)",
                                "create_email_test", args)
        if real_email and real_email.get('id'):
            tid = real_email['id']
            created_tests['email_tests'].append(tid)
            print(f"         Created email test ID: {tid}")

            await test_optional(session, f"get_email_test_spam_results({tid})",
                                "get_email_test_spam_results", {"test_id": tid},
                                reason="spam results not available yet")
            await test_optional(session, f"get_email_test_spam_seedlist({tid})",
                                "get_email_test_spam_seedlist", {"test_id": tid},
                                reason="no seed-based spam component on this test")
    else:
        skip("create_email_test (real)", "user declined")
        skip("get_email_test_spam_results", "no real email test created")
        skip("get_email_test_spam_seedlist", "no real email test created")

    # --- Reprocess Screenshots (auto-discover a completed test) ---
    print("\n--- Reprocess Screenshots ---")
    print("  NOTE: Reprocessing consumes a limited per-client reprocess quota")
    print("  and requires a COMPLETED test.")
    reprocess_target = None
    all_tests = await call_tool(session, "get_email_tests")
    if isinstance(all_tests, list):
        for t in all_tests[:5]:
            if t.get('type') != 'email-test':
                continue
            info = await call_tool(session, "get_email_test_info", {"test_id": t['id']})
            completed = (info or {}).get('completed', [])
            if completed:
                client = completed[0] if isinstance(completed[0], str) else completed[0].get('id')
                reprocess_target = (t['id'], client)
                break
    if reprocess_target:
        tid, client = reprocess_target
        confirm = input(f"  Reprocess client '{client}' on test {tid}?\n"
                        f"  This uses a reprocess credit. (y/n): ").strip().lower()
        if confirm in ('y', 'yes'):
            await test(session, f"reprocess_email_test_screenshots({tid}, ['{client}'])",
                       "reprocess_email_test_screenshots",
                       {"test_id": tid, "clients": [client]})
        else:
            skip("reprocess_email_test_screenshots", "user declined")
    else:
        skip("reprocess_email_test_screenshots",
             "no completed email test found in the 5 most recent")

    # --- Create Spam Test (sandbox) ---
    # Sandbox spam tests return a real, queryable ID (unlike sandbox email
    # tests), so they also cover the spam-test read tools for free. Using the
    # seed method makes the seedlist endpoint testable too.
    print("\n--- Create Spam Test (sandbox) ---")
    spam_args = {"subject": "MCPTEST_Spam", "html": TEST_HTML, "sandbox": True}
    if seed_key:
        spam_args["test_method"] = "seed"
        spam_args["key"] = seed_key
    created_spam = await test(session, "create_spam_test('MCPTEST_Spam', sandbox=True)",
                              "create_spam_test", spam_args)
    if created_spam and created_spam.get('id'):
        tid = created_spam['id']
        print(f"         Created sandbox spam test ID: {tid}")

        await test(session, f"get_spam_test_results({tid})",
                   "get_spam_test_results", {"test_id": tid})
        if seed_key:
            await test(session, f"get_spam_test_seedlist({tid})",
                       "get_spam_test_seedlist", {"test_id": tid})
        else:
            await test_optional(session, f"get_spam_test_seedlist({tid})",
                                "get_spam_test_seedlist", {"test_id": tid},
                                reason="test is not seed-based")
        created_tests['spam_tests'].append(tid)

    # --- Create Spam Test (real) ---
    print("\n--- Create Spam Test (real) ---")
    print("  WARNING: This will create a real spam test.")
    confirm = input("  Proceed? (y/n): ").strip().lower()
    if confirm in ('y', 'yes'):
        real_spam = await test(session, "create_spam_test('MCPTEST_Spam_Real')",
                               "create_spam_test",
                               {"subject": "MCPTEST_Spam_Real",
                                "html": TEST_HTML})
        if real_spam and real_spam.get('id'):
            created_tests['spam_tests'].append(real_spam['id'])
            print(f"         Created spam test ID: {real_spam['id']}")
    else:
        skip("create_spam_test (real)", "user declined")

    print_summary()

    # --- Cleanup ---
    await cleanup_created_tests(session)


# ============================================================================
# Full Tests (read-only + write operations)
# ============================================================================

async def run_full_tests(session):
    await run_readonly_tests(session)
    await run_write_tests(session)


# ============================================================================
# Cleanup
# ============================================================================

async def cleanup_created_tests(session):
    """Prompt user to delete tests created during the write test run.
    This doubles as the test of the delete_email_test / delete_spam_test tools."""
    total = len(created_tests['email_tests']) + len(created_tests['spam_tests'])

    if total == 0:
        print("\nNo real tests were created; nothing to clean up.")
        print("(delete_email_test / delete_spam_test not exercised this run.)")
        return

    print(f"\n{'=' * 60}")
    print("CLEANUP - DELETE CREATED TESTS")
    print(f"{'=' * 60}")
    print("\nThe following tests were created:")

    for tid in created_tests['email_tests']:
        print(f"  Email test ID: {tid}")
    for tid in created_tests['spam_tests']:
        print(f"  Spam test ID: {tid}")

    confirm = input(f"\nDelete all {total} created tests? (y/n): ").strip().lower()
    if confirm not in ('y', 'yes'):
        print("Skipping cleanup. You can delete these in the Email on Acid dashboard.")
        return

    print("\n--- Deleting created tests ---")

    for tid in created_tests['email_tests']:
        try:
            result = await call_tool(session, "delete_email_test", {"test_id": tid})
            if result and result.get('success'):
                print(f"  [DELETED] Email test {tid}")
            else:
                print(f"  [FAILED]  Email test {tid} - {result}")
        except Exception as e:
            print(f"  [FAILED]  Email test {tid} - {e}")

    for tid in created_tests['spam_tests']:
        try:
            result = await call_tool(session, "delete_spam_test", {"test_id": tid})
            if result and result.get('success'):
                print(f"  [DELETED] Spam test {tid}")
            else:
                print(f"  [FAILED]  Spam test {tid} - {result}")
        except Exception as e:
            print(f"  [FAILED]  Spam test {tid} - {e}")

    print("\nCleanup complete.")


# ============================================================================
# Main
# ============================================================================

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(SERVER_DIR, "server.py")
PYTHON = os.path.join(SERVER_DIR, ".venv", "bin", "python")


async def main():
    print("=" * 60)
    print("Email on Acid MCP Server - Tool Test Suite")
    print("=" * 60)
    print(f"\nSpawns the MCP server over stdio: {SERVER_SCRIPT}")
    print("Credentials: resolved by the server (.env file)")
    print("\n1. Read-only tests (safe, no modifications)")
    print("2. Write-only tests (create, update, delete)")
    print("3. Full tests (read-only + write operations)")

    choice = input("\nSelect test mode (1, 2, or 3): ").strip()

    python = PYTHON if os.path.exists(PYTHON) else sys.executable
    params = StdioServerParameters(command=python, args=[SERVER_SCRIPT],
                                   env={**os.environ})

    print(f"\nStarting MCP server: {python} {SERVER_SCRIPT}")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected.\n")

            if choice == '2':
                await run_write_tests(session)
            elif choice == '3':
                await run_full_tests(session)
            else:
                await run_readonly_tests(session)


if __name__ == '__main__':
    asyncio.run(main())
