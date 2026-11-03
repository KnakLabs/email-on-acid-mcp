# Email on Acid MCP Server

An MCP server exposing every documented [Email on Acid API v5](https://api.emailonacid.com/docs/) request as a tool — 24 tools across authentication, email client lists, email (rendering) testing, and spam testing. Built at [Knak](https://knak.com?utm_source=github&utm_medium=referral&utm_campaign=knak-labs-ong).

## Setup

Create a virtual environment and install dependencies (Python 3.12):

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Credentials

The server authenticates with HTTP Basic auth (`API key` as username, account password as password) and resolves credentials from `EOA_API_KEY` / `EOA_ACCOUNT_PASSWORD` environment variables — including values from a **`.env` file** in this directory, which is loaded automatically at startup. Copy `.env.example` to `.env` and fill in your key:

```bash
cp .env.example .env
# then edit .env:
# EOA_API_KEY=your_api_key
# EOA_ACCOUNT_PASSWORD=your_account_password   (omit if your account has none)
```

## Register with Claude Code

```bash
claude mcp add email-on-acid \
  -- /absolute/path/to/email-on-acid-mcp/.venv/bin/python \
     /absolute/path/to/email-on-acid-mcp/server.py
```

## Register with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "email-on-acid": {
      "command": "/absolute/path/to/email-on-acid-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/email-on-acid-mcp/server.py"]
    }
  }
}
```

## Tools

### Authentication
| Tool | API request |
|---|---|
| `verify_auth` | `GET /auth` |

### Email client lists
| Tool | API request |
|---|---|
| `get_available_email_clients` | `GET /email/clients` |
| `get_default_email_clients` | `GET /email/clients/default` |
| `set_default_email_clients` | `PUT /email/clients/default` |

### Email testing
| Tool | API request |
|---|---|
| `create_email_test` | `POST /email/tests` |
| `get_email_tests` | `GET /email/tests` |
| `search_email_tests` | `GET /email/tests?<query>` |
| `get_email_test_info` | `GET /email/tests/{test_id}` |
| `delete_email_test` | `DELETE /email/tests/{test_id}` |
| `get_email_test_results` | `GET /email/tests/{test_id}/results[/{client_id}]` |
| `reprocess_email_test_screenshots` | `PUT /email/tests/{test_id}/results/reprocess` |
| `get_email_test_content` | `GET /email/tests/{test_id}/content` |
| `get_email_test_content_inline_css` | `GET /email/tests/{test_id}/content/inlinecss` |
| `get_email_test_content_text_only` | `GET /email/tests/{test_id}/content/textonly` |
| `get_email_test_spam_results` | `GET /email/tests/{test_id}/spam/results` |
| `get_email_test_spam_seedlist` | `GET /email/tests/{test_id}/spam/seedlist` |

### Spam testing
| Tool | API request |
|---|---|
| `get_spam_clients` | `GET /spam/clients` |
| `create_spam_test` | `POST /spam/tests` |
| `get_spam_tests` | `GET /spam/tests` |
| `search_spam_tests` | `GET /spam/tests?<query>` |
| `get_spam_test_results` | `GET /spam/tests/{test_id}` |
| `delete_spam_test` | `DELETE /spam/tests/{test_id}` |
| `get_spam_test_seedlist` | `GET /spam/tests/{test_id}/seedlist` |
| `reserve_spam_seedlist` | `GET /spam/seedlist` |

## Testing

```bash
.venv/bin/python test_mcp_server.py
```

The test suite spawns the server over stdio (no separate server start needed) and offers three modes: read-only, write-only, or full. Test IDs are auto-discovered from the account or created during the run — no saved configuration is needed. Write tests default to sandbox mode (no test credits consumed) and prefix subjects with `MCPTEST_`; anything that costs a credit or quota (real email test with spam component, real spam test, screenshot reprocessing) asks for confirmation first, and created tests are deleted in a confirmed cleanup step at the end. Answering yes to all prompts in full mode exercises all 24 tools.

## Notes

- API errors are returned as `{"http_status": ..., "error": {...}}` rather than raised, so the calling agent can see the failure details.
- Test results are retained by Email on Acid for 90 days.
- `search_email_tests` / `search_spam_tests` use `from_date` / `to_date` parameter names (mapped to the API's `from` / `to`) because `from` is reserved in Python.
- Enterprise-only parameters (`reference_id`, `customer_id`, `headers` x-headers) are included but will be ignored or rejected on non-enterprise plans.

## Built at Knak

[Knak](https://knak.com?utm_source=github&utm_medium=referral&utm_campaign=knak-labs-ong)
is the agentic production layer for enterprise marketing: where marketers and AI
agents build on-brand emails and landing pages, then sync them to the team's
marketing automation platform.

We use this server to put Email on Acid's rendering and spam checks in front of
an agent, so a build can be tested without leaving the conversation.
