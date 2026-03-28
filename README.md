### Ask ALYF

Helps you understand ERPNext

### Features

This app adds a chat bubble to the ERPNext interface where you can talk to an agent that knows everything about your ERPNext instance. It has two modes: Ask and Agent.

- Ask mode: Ask questions about your ERPNext instance — data, configuration, code, docs — and the agent answers.
- Agent mode: Ask the agent to create, update, submit, cancel, or delete documents for you. Every mutation requires explicit user confirmation before execution.

The agent supports multi-turn tool calls (chaining multiple operations in one response) and renders responses as Markdown (tables, code blocks, bold, etc.). Responses are streamed to the chat bubble via socket.io.

Input can be text or voice. Voice input is transcribed to text before being sent to the agent; the agent's response can optionally be read aloud via text-to-speech.

### Staying Close to Frappe

Ask ALYF tries to stay close to the Frappe Framework instead of inventing a parallel experience. It uses a familiar UI, integrates native building blocks like **Frappe Charts** and the standard file uploader, and stays within the same role-based permission system instead of bypassing framework permissions.

### Tools

All data-access tools wrap `frappe.client` functions, which enforce the same permission checks as the REST API. The agent can only do what the logged-in user can already do via the API.

#### Ask mode

Data retrieval (from `frappe.client`):

- `get_list` — list records with filters, fields, ordering, pagination, and `group_by` for aggregation
- `get_count` — count records matching filters
- `get` — get a single document (perm-checked, field-level read permissions applied)
- `get_value` — get specific field value(s) from a document
- `get_single_value` — get a field value from a Single DocType

Schema and permissions:

- `get_meta` — get DocType metadata (fields, types, options, permissions)
- `has_permission` — check if current user has a specific permission on a document
- `get_doc_permissions` — get the full evaluated permission dict for a document
- `list_accessible_doctypes` — get list of DocTypes the current user can read or write
- `list_accessible_reports` — get list of reports the current user can access
- `translate_ui_labels` — translate UI labels/terms so responses use the same wording the user sees in their language

Code search (when enabled):

- `source_code_analyzer` — delegate code questions to a restricted specialist that can search, list, and read installed app files, then return a grounded summary with evidence

App metadata and documentation:

- `get_app_version` — useful for comparing your current version with available releases
- `read_github_releases` — uses the Repository URL from `pyproject.toml` `[project.urls]`
- `read_documentation_page` — read official docs using the Documentation URL from `pyproject.toml` `[project.urls]`

Printing:

- `get_print` — generate a PDF print of a document using the default (or specified) print format and letter head; respects `print` permission and the document's `language` field; the PDF is attached to the conversation and shown as a clickable file

Files:

- `get_file_id` — resolve a **File** ID from attachment references
- `read_file_record` — read file content from **File** records by File ID
- `extract_document_data` — extract structured data from PDF or image **File** records

SQL (Administrator and System Manager only):

- `run_read_only_sql` — run read-only SQL queries, similar to the existing **System Console**

Frontend actions:

- `set_route` — navigate to a Desk route
- `new_doc` — open a new document form, optionally with prefilled route options
- `scroll_to_field` — scroll to a field on the active form

#### Agent mode

Everything from Ask mode, plus:

- `document_planner` — prepare `insert`, `save`, or `set_value` payloads using read-only metadata and record lookups before the main agent creates a pending proposal
- `insert` — create a new document
- `save` — update an existing document
- `set_value` — set specific field(s) on a document
- `submit` — submit a submittable document
- `cancel` — cancel a submitted document
- `amend` — amend a cancelled document (cancel + create amended copy)
- `delete` — delete a document (framework requires cancel before delete for submitted docs; some documents cannot be deleted due to links, e.g. cancelled invoices linked to submitted payment ledger entries)
- `rename_doc` — rename a document
- `attach_file` — attach a file to a document by File ID
- `run_whitelisted_method` — call any `@frappe.whitelist()` method the current user has access to (e.g. `erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice`)
- `frm_set_value` — set a field on the active form in the browser
- `frm_add_child` — add a child table row on the active form in the browser

#### Charts

- `show_chart` — display one or more **Frappe Charts** under the assistant message (validated on the server, stored on message metadata, rendered below the reply; auto-run in the browser like other safe frontend actions)

#### Context on every request

- current user's route
- current document `doctype` and `name` (if on a form view)
- current list view filters (if on a list view)
- user's Frappe language (`frappe.boot.lang`)
- `frappe.boot.user.defaults`
- user's roles (omitted for Administrator)

### Guardrails

- **Confirmation before mutations**: Every write operation (create, update, delete, submit, cancel, amend, rename) requires explicit user confirmation before execution. The agent proposes the action, the user approves or rejects.
- **No bulk operations**: The agent cannot use `insert_many`, `bulk_update`, or batch deletes. Every mutation is a single confirmed operation.
- **Framework constraints respected**: The agent does not bypass framework validation. For example, it cannot delete a submitted document without cancelling it first, and it cannot delete cancelled documents that have linked submitted entries.
- **Configurable DocType exclusions**: Admins can exclude specific DocTypes from Agent mode via **Ask ALYF Settings**.

### Security

The agent has the same permissions as the current user. If you're logged in as a HR Manager, the agent can only do HR stuff. If you're logged in as Administrator, the agent can do anything. This is enforced by `frappe.client` and the framework's permission system on every tool call.

SQL queries are restricted to read-only and only available to users with the Administrator or System Manager role.

### Conversation History

Conversations are persisted in an **Ask ALYF Conversation** DocType. This provides:

- conversation continuity across page reloads
- an audit trail of what the agent did, especially for Agent mode actions
- data for usage analytics and debugging

Old conversations are automatically deleted after 90 days by default. The retention period is configurable per site via **Log Settings**.

### Configuration

**Ask ALYF Settings** (Single DocType):

- LLM provider
- API key
- model name
- enable / disable Agent mode (site-wide kill switch)
- roles that can use the agent
- DocTypes excluded from Agent mode

### Error Handling

- Tool failures (permission denied, validation errors, missing records) are surfaced as clear messages to the user, not raw tracebacks.
- LLM API errors (unreachable, rate-limited) show a retry prompt.
- If the agent references a DocType or field that doesn't exist, it re-checks via `get_meta` before retrying.

### Voice

- **Voice input**: A microphone button in the chat bubble records audio and transcribes it to text using the browser's [Web Speech API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API) (SpeechRecognition). Falls back to server-side transcription (e.g. OpenAI Whisper) if the browser doesn't support it.
- **Voice output**: The agent's response can be read aloud using the browser's [SpeechSynthesis API](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis). This is opt-in via a speaker button on each message or a toggle in the chat header.

### Dependencies

- [any-agent](https://mozilla-ai.github.io/any-agent/) for the agent framework (limited to openai-agents for now)
- [deep-chat](https://deepchat.dev/) for the chat bubble UI — a framework-agnostic web component with built-in Markdown rendering, streaming support via handler API (wired to socket.io), and microphone input.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app ask_alyf
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/ask_alyf
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

gpl-3.0
