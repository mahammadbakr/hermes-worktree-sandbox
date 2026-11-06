# Hermes Agent Plugin System & Catalog Research

> **Date:** November 6, 2026  
> **Target:** Hermes Agent Plugin Hackathon by Nous Research (Deadline: Nov 11, 2026 @ 5:00 PM EST)  
> **Primary Sources Verified:**
> - Developer Guide (`https://lnkd.in/dkE5EUHQ` → `https://hermes-agent.nousresearch.com/docs/developer-guide/plugins` and all 19 sub-guides)
> - Catalog Submission Guide (`https://lnkd.in/dnYCc5bf` → `https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission`)
> - Public Plugin API (`https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/public-api`)
> - Live Catalog Index (`https://hermes-agent.nousresearch.com/docs/api/plugin-catalog.json` — 1,063 listed plugins as of Nov 6, 2026)
> - Canonical Repo Files via GitHub API (`NousResearch/hermes-agent`: `plugin-catalog/README.md`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/workflows/plugin-catalog-ci.yml`, `scripts/validate_plugin_catalog.py`, `hermes_cli/plugins.py`, `hermes_cli/plugin_validate.py`, `hermes_cli/plugins_manifest.py`, `hermes_cli/plugins_registrars.py`)

---

## 0. Access & Environment Audit (No Silent Assumptions)

1. **Shortlink Resolution:** Both LinkedIn shortlinks (`https://lnkd.in/dkE5EUHQ` and `https://lnkd.in/dnYCc5bf`) serve a LinkedIn external-link interstitial that resolves to `https://hermes-agent.nousresearch.com/docs/developer-guide/plugins` and `https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission`. Both target pages and their linked sub-pages were fetched in full.
2. **GitHub Raw Rate Limit Bypass:** Direct unauthenticated fetches to `raw.githubusercontent.com` returned HTTP 429; we bypassed this cleanly using the authenticated `gh api` CLI (`gh api repos/NousResearch/hermes-agent/contents/...`) to inspect the exact source code in `NousResearch/hermes-agent` and community plugin repositories.
3. **Local Machine State (`darwin` / macOS):**
   - `gh` (`/usr/local/bin/gh`) and `python3` (`/usr/local/bin/python3`) are installed.
   - `hermes` and `uv` are **not currently on `PATH`** in this shell. To run `hermes plugins validate /path/to/plugin --install-deps` and `hermes plugins doctor . --ci` locally before opening our catalog PR, we will either need to locate an existing Hermes checkout/install on disk or clone `NousResearch/hermes-agent` and activate its PM developer environment (`source ./activate`).

---

## 1. Extension Points Hermes Actually Supports

Hermes plugins are loaded by `PluginManager` (`hermes_cli/plugins.py`) from `~/.hermes/plugins/<name>/` (user), `./.hermes/plugins/<name>/` (project, gated by `HERMES_ENABLE_PROJECT_PLUGINS=1`), `<repo>/plugins/<name>/` (bundled), or `hermes_agent.plugins` pip entry points. Every native Python plugin exposes `def register(ctx: PluginContext) -> None` in `__init__.py`.

### 1.1 General `PluginContext` (`ctx`) Surface (`hermes_cli/plugins.py`)

| Extension Point | `ctx` Method / Property | Contract & Behavior | Citation |
|---|---|---|---|
| **Agent Tools** | `ctx.register_tool(name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False, description="", emoji="", override=False)` | Registers an LLM-callable tool. `handler(args: dict, **kwargs) -> str` **must** return a JSON string and never raise. `override=True` replaces a built-in tool only if `capabilities: [tools.override]` is declared and granted. | `hermes_cli/plugins.py:204-241`, `docs/developer-guide/plugins` |
| **Lifecycle & Observer Hooks** | `ctx.register_hook(hook_name, callback, *, hold_stream=False)` | Subscribes to `VALID_HOOKS` (33 hooks total). Callbacks must accept `**kwargs`. Fail-open on error (except `pre_tool_call` timeout, which fails closed with a block). `hold_stream=True` on `transform_llm_output` suppresses token streaming until the hook rewrites the final reply. | `hermes_cli/plugins.py:114-186, 675-678`, `docs/developer-guide/observer-hooks` |
| **Behavior-Changing Middleware** | `ctx.register_middleware(kind, callback)` | 4 kinds in `VALID_MIDDLEWARE`: `tool_request` (returns `{"args": ...}` before guardrails/approvals), `llm_request` (returns `{"request": ...}` before provider call), `tool_execution` (wraps `next_call(args)`), `llm_execution` (wraps `next_call(request)`). | `hermes_cli/plugins.py:679-685`, `docs/developer-guide/middleware` |
| **In-Session Slash Commands** | `ctx.register_command(name, handler, description="", args_hint="", argument_mode=None)` | Registers `/name` across CLI, TUI, Desktop, and Messaging Gateways (Telegram, Discord, Slack, etc.). Handler receives `raw_args: str` plus optional `session_id`, `session_key`, `platform`, `source`. Cannot shadow built-in commands. | `hermes_cli/plugins.py:390-416`, `docs/developer-guide/plugins#register-slash-commands` |
| **Terminal CLI Subcommands** | `ctx.register_cli_command(name, help, setup_fn, handler_fn=None, description="")` | Adds `hermes <name> <subcommand>` via `argparse` `setup_fn(subparser)`. | `hermes_cli/plugins.py:376-388`, `docs/developer-guide/plugins#register-cli-commands` |
| **System Prompt Sections** | `ctx.register_system_prompt_section(id, content, *, position="after_memory", max_chars=...)` | Freezes bounded static or callable(`session_info`) instructions into new session system prompts without breaking prompt-cache prefixes mid-session. | `hermes_cli/plugins.py:699-725` |
| **Context References (`@prefix:`)** | `ctx.register_context_reference(provider)` | Subclass `agent.context_references.ContextReferenceProvider`. Expands `@<prefix>:<query>` tokens in user prompts with autocomplete in TUI and Desktop composer. Cannot shadow `diff`, `staged`, `file`, `folder`, `git`, `url`. | `hermes_cli/plugins.py:450-464` |
| **Bundled Skills** | `ctx.register_skill(name, skill_md_path, description="")` | Exposes read-only `<plugin>:<skill>` skills loadable via `skill_view()`. | `hermes_cli/plugins_content.py`, `docs/developer-guide/plugins#bundle-skills` |
| **Automation Blueprints** | `ctx.register_automation_blueprint(key, *, title, description, schedule_template, prompt_template, ...)` | Adds parameterized cron templates (`/blueprint <plugin>:<key>`) to CLI, TUI, Desktop Cron page, and Dashboard. | `hermes_cli/plugins_content.py`, `docs/developer-guide/plugins#add-automation-blueprints` |
| **Host-Owned LLM Calls** | `ctx.llm.complete(...)`, `ctx.llm.complete_structured(...)`, `acomplete(...)`, `acomplete_structured(...)` | Out-of-band LLM calls using the user's active model/auth without touching credentials. Supports `json_schema` validation and image inputs. Can route to custom `ctx.register_auxiliary_task(key, ...)`. | `hermes_cli/plugins.py:118-125, 595-616`, `docs/developer-guide/plugin-llm-access` |
| **Session Side-Questions** | `ctx.side_question(token, prompt, timeout=15)` | Uses `side_question_token` from `post_llm_call` to ask the session's warm-cache agent a follow-up question without writing to the transcript. Requires `capabilities: [llm.side_question]`. | `docs/developer-guide/plugin-llm-access#asking-the-sessions-own-agent-ctxside_question` |
| **Subagent Lifecycle** | `ctx.subagent_lifecycle` (`launch`, `status`, `wait`, `steer`, `cancel`, `result`, `reconnect`) | Launches and supervises isolated child sessions with serializable `SubagentHandle` capabilities during an active turn. | `hermes_cli/plugins.py:128-132`, `docs/developer-guide/subagent-lifecycle-api` |
| **Tool Dispatch & MCP** | `ctx.dispatch_tool(tool_name, args, **kwargs)` / `ctx.call_mcp(server, tool, arguments, timeout=30)` | Invokes any registered tool through Hermes's approval/redaction pipeline, or calls an operator-allowlisted MCP server. | `hermes_cli/plugins.py:243-273, 417-426` |
| **Interactive User Choice** | `ctx.ask_choice(question, choices)` | Blocks inside a sync slash-command handler to render native choice buttons (Telegram/Discord/Slack) or the TUI/Desktop clarify picker. | `hermes_cli/plugins.py:359-364` |
| **Session & Message Injection** | `ctx.post_message(text)` / `ctx.apost_message(text)` / `ctx.inject_message(content, role="user", ...)` | Posts updatable status messages (`handle.edit(text)`) or queues user turns into a live TUI/Desktop/Gateway session. | `hermes_cli/plugins.py:329-357` |
| **Approval Transports** | `ctx.register_approval_transport(name, present_fn)` | Registers a custom human-approval transport (`security.approval.transport: <name>`) receiving redacted `ApprovalRequest` objects. | `hermes_cli/plugins.py:178-201` |
| **Secret Redaction** | `ctx.register_redaction_patterns(patterns)` | Additively registers regexes with `agent.redact` so custom tokens never leak into logs or transcripts. | `hermes_cli/plugins.py:618-630` |
| **Plugin Config & Durable State** | `ctx.get_config(key, default)`, `ctx.set_config(key, value)`, `ctx.state`, `plugin_data_dir(name)`, `plugin_db(name)` | Profile-scoped settings (`plugins.entries.<id>.settings`), atomic JSON state (`ctx.state`, 10 MiB cap), and WAL-mode SQLite storage (`<HERMES_HOME>/plugin-data/<id>/data.db`). | `hermes_cli/plugins.py:7-27`, `plugins/plugin_storage.py` |
| **Inter-Plugin Event Bus & Desktop Push** | `ctx.emit(event, payload)`, `ctx.subscribe("<plugin>:<event>", cb)`, `broadcast_plugin_event(plugin_id, event, payload)` | In-process pub/sub across plugins (`ctx.emit`) and live WebSocket broadcast (`plugin.<id>.<event>`) to connected Hermes Desktop and TUI clients. | `hermes_cli/plugins.py:726-754`, `hermes_cli/plugin_events.py` |

### 1.2 All 33 Valid Lifecycle Hooks (`VALID_HOOKS` in `hermes_cli/plugins.py:114-186`)

- **Tool Lifecycle:** `pre_tool_call` (can return `{"action": "block", "message": ...}`, `{"action": "approve", "message": ..., "rule_key": ...}`, or `{"action": "modify", "args": ...}`), `post_tool_call`, `transform_terminal_output`, `transform_tool_result`
- **Turn & Output Lifecycle:** `pre_llm_call` (can return `{"context": ...}` to inject into user message or `{"action": "block", "message": ...}` to veto the turn before inference), `post_llm_call`, `transform_llm_output` (supports `hold_stream=True`), `pre_verify` (can return `{"action": "continue", "message": ...}` when agent edited code and is about to finish)
- **Streaming Observers:** `on_stream_start`, `on_stream_delta`, `on_stream_end`, `on_interim_message`
- **Raw Provider API Observers:** `pre_api_request`, `post_api_request`, `api_request_error`, `pre_auxiliary_call`, `post_auxiliary_call`, `transform_api_error_classification`
- **Session & Compaction Lifecycle:** `on_session_start`, `on_session_end`, `on_session_finalize`, `on_session_reset`, `on_session_delete`, `post_compaction`, `agent_loop_stopped`
- **Subagent & Skill Lifecycle:** `subagent_start`, `subagent_stop`, `on_skill_lifecycle`
- **Human Input & Approvals:** `pre_approval_request`, `post_approval_response`, `on_human_input_request`, `on_human_input_resolved`
- **Gateway, Voice & Kanban:** `pre_gateway_dispatch` (can `skip` or `rewrite` inbound message), `post_gateway_admission`, `gateway_platform_event`, `pre_command`, `pre_transcription`, `on_room_member_activity`, `kanban_task_claimed`, `kanban_task_completed`, `kanban_task_blocked`, `on_kanban_worker_spawned`, `on_kanban_worker_exited`, `on_kanban_worker_stale_claim`, `on_kanban_task_updated`, `on_kanban_dispatch_tick`

### 1.3 Specialized Provider Plugins (`hermes_cli/plugins_registrars.py` & `hermes_cli/plugins.py`)

| Provider Type | Registration Call | ABC / Base Class | Activation Config |
|---|---|---|---|
| **Memory Provider** | `ctx.register_memory_provider(provider)` | `agent.memory_provider.MemoryProvider` | `memory.provider: <name>` (supports API v2 fail-closed `on_pre_compress` checkpoints, `prefetch`, `sync_turn`, `on_memory_write`, `cli.py`) |
| **Context Engine** | `ctx.register_context_engine(engine)` | `agent.context_engine.ContextEngine` | `context.engine: <name>` (supports `should_compress`, `compress`, plus per-turn `select_context()` and `on_turn_complete()` with stable `message_uid`) |
| **Terminal Environment** | `ctx.register_terminal_environment_provider(provider)` | `agent.terminal_env_provider.TerminalEnvironmentProvider` + `tools.environments.BaseEnvironment` | `terminal.backend: <name>` (routes `terminal`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`) |
| **Delegation Strategy** | `ctx.register_delegation_provider(provider)` | `agent.delegation_provider.DelegationProvider` | `delegation.backend: <name>` (adds custom schema params to `delegate_task` and routes each child task to a model/provider/tier or Hermes profile) |
| **Model Provider** | `providers.register_provider(ProviderProfile(...))` at import | `providers.base.ProviderProfile` (or `agent.acp_client.ACPClient`) | `kind: model-provider` in `plugin.yaml`; `model.provider: <name>` |
| **Computer-Use Driver** | `ctx.register_computer_use_provider(provider)` | `tools.computer_use.backend.ComputerUseProvider` | `computer_use.backend: <name>` |
| **Web Search / Extract** | `ctx.register_web_search_provider(provider)` | `agent.web_search_provider.WebSearchProvider` | `web.search_backend` / `web.extract_backend` |
| **Cloud Browser** | `ctx.register_browser_provider(provider)` | `agent.browser_provider.BrowserProvider` | `browser.cloud_provider: <name>` |
| **Image / Video Gen** | `ctx.register_image_gen_provider` / `ctx.register_video_gen_provider` | `ImageGenProvider` / `VideoGenProvider` | `image_gen.provider` / `video_gen.provider` |
| **TTS / STT** | `ctx.register_tts_provider` / `ctx.register_transcription_provider` | `TTSProvider` / `TranscriptionProvider` | `tts.provider` / `stt.provider` |
| **Secret Source** | `ctx.register_secret_source(source)` | `agent.secret_sources.base.SecretSource` | `secrets.<name>.enabled: true` |
| **Gateway Platform** | `ctx.register_platform(...)` or `ctx.register_platform_handler(platform, factory)` | `gateway.platforms.base.BasePlatformAdapter` | `kind: platform` or hooks onto existing Telegram/Discord/Slack/Matrix adapters |
| **Dashboard Auth** | `ctx.register_dashboard_auth_provider(provider)` | `hermes_cli.dashboard_auth.DashboardAuthProvider` | Web dashboard OIDC/auth gate |

### 1.4 Native Desktop Plugin SDK (`desktop/plugin.js`) & Unified Packages

A plugin can ship **both** an agent backend (`plugin.yaml` + `__init__.py` + optional `dashboard/manifest.json` & `dashboard/plugin_api.py` mounting FastAPI routes at `/api/plugins/<id>/`) **and** a native Hermes Desktop frontend at `desktop/plugin.js` (`docs/developer-guide/desktop-plugin-sdk#one-package-both-sdks`):
- `desktop/plugin.js` is a plain uncompiled ESM module (`import { ... } from '@hermes/plugin-sdk'`, `import { useState, ... } from 'react'`, `import { jsx, jsxs } from 'react/jsx-runtime'`). **No JSX syntax** and no other imports are allowed.
- **Contribution areas:**
  - `PANES_AREA` (`'panes'`): dockable layout tiles (`left`, `right`, `top`, `bottom`, `main`)
  - `ROUTES_AREA` + `SIDEBAR_NAV_AREA`: full workspace pages + sidebar navigation
  - `STATUSBAR_AREAS.left` / `.right` and `TITLEBAR_AREAS`: live status chips and popovers
  - `PALETTE_AREA` + `KEYBINDS_AREA`: ⌘K commands and user-rebindable shortcuts
  - `COMPOSER_AREAS` (`top`, `bottom`, `underside`, `leading`, `actions`, `attachments`, `middleware`, `contextMenu`, `modelPill`) + `host.composer` (`getDraft`, `setDraft`, `insertText`, `submit`, `focus`)
  - `TRANSCRIPT_DIRECTIVE_AREA`: inline interactive React components in assistant messages when the model emits `::name{key="value"}`
  - `TOOL_MEDIA_RENDERER_AREA` (`'transcript.toolMedia'`): custom media player/viewer cards for `MEDIA:` files produced by the plugin's own tools
  - `SESSION_ROW_AREAS`, `KANBAN_CARD_AREAS.badges`, `MODEL_MENU_ROW_AREA`, `THEMES_AREA`, `SETTINGS_PLUGINS_AREA` (`ctx.registerSettingsPage`), ` ctx.pet.say()`
- **Real-time Reactivity:** Python hooks/tools call `from hermes_cli.plugin_events import broadcast_plugin_event; broadcast_plugin_event("<id>", "event.name", payload)` and `desktop/plugin.js` subscribes via `ctx.onEvent('plugin.<id>.event.name', handler)` + `ctx.rest('/route')`.

---

## 2. Exact Manifest & Catalog Metadata Formats

### 2.1 Plugin Manifest (`plugin.yaml` — v1/v2)

Verified from `hermes_cli/plugins_manifest.py` and `hermes_cli/plugin_validate.py`:

```yaml
name: my-plugin                  # REQUIRED: [a-z0-9_-]{1,64}
version: "1.0.0"                 # REQUIRED: SemVer string
description: "..."               # REQUIRED: non-empty summary
manifest_version: 2              # Optional (default 1, max 2)
api_version: 1                   # Optional
kind: standalone                 # Optional: standalone | backend | exclusive | platform | model-provider
author: "Your Name"              # Optional
license: MIT                     # Optional (SPDX identifier)
homepage: "https://github.com/owner/my-plugin"
requires_hermes: ">=0.22.5"      # Optional SemVer comparator (MUST parse cleanly; match catalog entry)
platforms: [linux, macos, windows] # Optional
tags: [tools, desktop]           # Optional list of strings

# Capability & Registration Declarations (MUST match what register(ctx) actually registers!)
provides_tools: []               # Exact tool names registered via ctx.register_tool()
provides_hooks: []               # Exact hook names registered via ctx.register_hook()
provides_middleware: []          # Exact middleware kinds registered via ctx.register_middleware()
requires_env: []                 # UPPER_SNAKE_CASE strings or {name, description, url, secret} dicts
capabilities: []                 # Privileged host capabilities: tools.override, llm.side_question, etc.
python_dependencies: []          # PEP 508 strings with upper bounds (e.g. "httpx>=0.27,<1.0")
config_schema:                   # Renders automatically in Desktop Settings -> Plugins!
  my_setting:
    type: str                    # str | int | float | bool | list | dict | secret
    default: "val"
    label: "My Setting"
    description: "Help text"
    required: false
```

### 2.2 Catalog Entry (`plugin-catalog/<name>.yaml` in `NousResearch/hermes-agent`)

Verified from `scripts/validate_plugin_catalog.py` and `plugin-catalog/README.md`:

```yaml
name: my-plugin                  # REQUIRED: [a-z0-9_-]{1,64}
repo: https://github.com/owner/my-plugin  # REQUIRED: https:// git URL (GitHub/GitLab)
sha: 0123456789abcdef0123456789abcdef01234567  # REQUIRED: exact 40-char lowercase hex commit SHA
description: >-                  # REQUIRED: One-line description + "Disclosure — ..." section
  Concise summary of what the plugin does. Disclosure — exact statement of network calls,
  local storage paths, subprocesses, model calls, or "no network calls, no subprocesses,
  stores state only in $HERMES_HOME/plugin-data/my-plugin/".
maintainer: github-handle        # REQUIRED: repo owner / maintainer handle
tier: community                  # community (official/verified set by Nous maintainers only)
category: tools                  # desktop | memory | platform | web | tools | voice | automation | models | general
requires_hermes: ">=0.22.5"      # Optional SemVer floor (must match plugin.yaml)
version: "0.1.0"                 # Optional quoted version string matching plugin.yaml
title: "My Plugin"               # Optional display title on cards
docs_url: "https://github.com/owner/my-plugin#readme"
image: "https://raw.githubusercontent.com/owner/my-plugin/<40-char-sha>/assets/banner.png" # Optional 2:1 banner pinned to SHA
screenshots:                     # Optional up to 6 URLs on *.githubusercontent.com pinned to SHA
  - "https://raw.githubusercontent.com/owner/my-plugin/<40-char-sha>/assets/screen1.png"
readme: true                     # Optional boolean (default true)
platforms: []                    # Optional subset of [linux, macos, windows]; empty = all
capabilities:                    # MUST match plugin.yaml and actual registrations
  provides_tools: []
  provides_hooks: []
  provides_middleware: []
  requires_env: []
```

---

## 3. Case Studies of 5 Existing Catalog Plugins

We inspected the source trees and catalog entries of 5 top plugins across categories:

1. **`bubblewrap` (`NousResearch/hermes-official-plugins/tree/main/bubblewrap`, Official, `tools`)**
   - **What makes it great:** Uses `ctx.register_terminal_environment_provider()` + `ctx.register_system_prompt_section()`. Zero external Python dependencies. Lazy-imports `sandbox.py` inside functions so `register(ctx)` is instantaneous and never slows down CLI startup. Implements `is_available()`, `probe()`, `doctor_checks()`, `setup_instructions()`, and `post_setup()`. Dynamically injects a system prompt section only when `terminal.backend == "bubblewrap"` so the LLM understands its sandbox boundaries and doesn't waste turns trying to work around read-only paths.
2. **`advanced-delegation` (`NousResearch/hermes-official-plugins/tree/main/advanced-delegation`, Official, `tools`)**
   - **What makes it great:** Combines `ctx.register_delegation_provider()` (registering two providers: `model_map` and `profile_routes`), `ctx.register_command("delegation", ...)` (slash command with `--now` live toolset rebuild), and `ctx.register_cli_command("delegation", ...)` (interactive terminal setup). Defensive `ModuleNotFoundError` guard in `register(ctx)` logs a clean warning on older Hermes versions instead of crashing.
3. **`hermes-memory-wiki` (`NousResearch/hermes-official-plugins/tree/main/memory-wiki`, Official, `desktop`)**
   - **What makes it great:** Unified package combining `plugin.yaml`, `__init__.py`, `dashboard/manifest.json`, `dashboard/plugin_api.py` (FastAPI `APIRouter` reading `hermes_state.SessionDB` read-only with `?profile=` scoping), and `desktop/plugin.js` (native Desktop page + sidebar nav + command palette). Zero LLM calls, deterministic extraction, clean read-only safety posture.
4. **`hermes-session-diff` (`Adolanium/hermes-session-diff`, Community, `desktop` + `middleware`)**
   - **What makes it great:** Uses `pre_llm_call` hook + `tool_execution` middleware to snapshot files before/after tool calls into a local SQLite database (`$HERMES_HOME/plugin-data/hermes-session-diff/changes.sqlite3`), paired with a native `desktop/plugin.js` right-hand pane and `dashboard/plugin_api.py`. Its README is exemplary: hero image, 60-second MP4 demo link, 4-step "Try it" guide, explicit privacy/storage limits, and zero external dependencies.
5. **`epistemic-harness` (`quangphucqp/epistemic-harness`, Community, `general`)**
   - **What makes it great:** Deep multi-surface integration: 3 tools (`epistemic_model`, `epistemic_probe`, `epistemic_methods`), 6 hooks (`pre_llm_call`, `post_tool_call`, `transform_tool_result`, `subagent_stop`, `on_session_reset`, `on_session_finalize`), `tool_execution` middleware, and bundled skills. Demonstrates how a plugin enforces stateful reasoning discipline across turns and subagents—something a prompt or skill alone cannot enforce because the middleware and `pre_verify`/`transform_tool_result` hooks gate tool execution in Python.

---

## 4. Local Validation, Testing & Catalog CI Pipeline

### 4.1 Local Validation Commands
1. **Isolated Doctor Check:** `hermes plugins doctor /path/to/plugin --ci`  
   Runs directory discovery, manifest parsing, namespaced import, `register(ctx)`, and hook/tool registries in a temporary `HERMES_HOME` while blocking direct socket connections during `register()`.
2. **Admission Validator:** `hermes plugins validate /path/to/plugin --install-deps`  
   Runs the exact 14 checks executed by catalog CI (`hermes_cli/plugin_validate.py`):
   - `manifest` & `manifest fields` (`name`, `version`, `description`)
   - `requires_hermes` SemVer comparator parsing
   - `config schema` type validation
   - `requires_env` `UPPER_SNAKE_CASE` validation
   - `oauth` HTTPS and declared env var checks
   - `loadable` (`__init__.py`, `desktop/plugin.js`, `plugin.json`, or `locales/`)
   - `python dependencies` PEP 508 check
   - `capability probe` (spawns isolated `python -P -c` subprocess, imports `__init__.py`, runs `register(RecordingContext())` with 30s timeout, and fails if any tool, hook, or middleware registered is missing from `provides_tools`, `provides_hooks`, or `provides_middleware`)
   - `built-in tool collisions` (ensures no tool collides with core tools like `terminal`, `read_file`, `write_file`, `delegate_task`, etc.)
   - `security scan` (`tools.plugin_guard.scan_plugin`: `dangerous` fails admission; `caution` emits reviewer warnings)
   - `no core override` (`check_core_override`: rejects monkey-patching `AIAgent`, `setattr`, `sys.modules` tampering)
   - `private imports` (`check_private_imports`: warns on any Hermes import not in `hermes_cli/data/plugin_api.json`)
   - `desktop surface` (`check_desktop_surface`: rejects `eval`, `new Function`, non-SDK imports, `document.querySelector('[data-slot]')`, `MutationObserver` on `document.body`, raw `<webview>`)

### 4.2 Catalog PR CI (`plugin-catalog-ci.yml`)
When we open a PR to `NousResearch/hermes-agent` adding `plugin-catalog/<our-plugin>.yaml`:
1. **PR Scope Guard:** The PR **must only touch `plugin-catalog/<name>.yaml`** (and optionally `contributors/emails/**`). Any other modified file fails CI immediately.
2. **Job 1 (`structural`):** Runs `python3 scripts/validate_plugin_catalog.py plugin-catalog/` to verify YAML syntax, required keys, regexes, image URL hosts (`raw.githubusercontent.com` pinned to the SHA), and capability key types.
3. **Job 2 (`pinned-source-validate`):**
   - Clones `repo` from GitHub, verifies `sha` is a reachable 40-char commit object (not a tag or branch), and checks out `--detach $SHA`.
   - Verifies all symlinks stay inside the clone.
   - Runs `hermes plugins validate --install-deps "$PLUGIN_DIR"`.
   - Runs `scripts/scan_plugin_payloads.py` (Rule 17: rejects any compiled binary ELF/Mach-O/PE/Wasm, `.pyc`, or opaque archive).
   - Runs the self-updater grep gate (Rule 3: rejects JS/TS files that both reference GitHub release/raw URLs and call file-write APIs).

---

## 5. Hard Constraints & Security Rules (The 18 Admission Rules)

1. **Public surfaces only (Rule 9):** Only import modules listed in the [Public Plugin API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/public-api) (`agent.*` provider ABCs, `hermes_cli.config`, `hermes_cli.plugin_events`, `hermes_state`, `plugins.plugin_storage`, `plugins.plugin_utils`, `tools.registry`, etc.). Never patch core classes or private dicts.
2. **Exact capability parity (Rule 6):** `provides_tools`, `provides_hooks`, `provides_middleware`, and `requires_env` in both `plugin.yaml` and `plugin-catalog/<name>.yaml` must match what `register(ctx)` registers 1-to-1.
3. **Zero credential file access (Rule 11):** Never read `.env`, `~/.hermes/auth.json`, `~/.codex/auth.json`, keychains, or browser profiles. Read declared secrets exclusively via `from agent.secret_scope import get_secret`.
4. **Respect approvals & unattended runs (Rule 12):** Never bypass Hermes approvals or hang waiting for interactive input during cron, gateway, or subagent runs (`ctx.ask_choice` returns `None` in unattended runs; handle `None` gracefully).
5. **Desktop SDK strictness (Rule 8):** `desktop/plugin.js` must be uncompiled ESM using `jsx`/`jsxs` from `react/jsx-runtime`, importing only `@hermes/plugin-sdk`, `react`, and `react/jsx-runtime`, using CSS theme variables (`var(--ui-*)`), and disposing all listeners/timers via `ctx.onDispose` / `ctx.onEvent`.
6. **No binaries or `.pyc` files (Rule 17) & No self-updaters (Rule 3).**
7. **Complete Disclosure in Catalog Entry & README (Rule 13):** Explicitly state whether the plugin makes network calls, spawns subprocesses, makes auxiliary LLM calls, or writes to `$HERMES_HOME/plugin-data/<name>/`.
8. **Dependency Bounds (Rule 10):** Prefer zero external Python dependencies (using Python stdlib + modules Hermes already ships like `httpx`, `fastapi`, `ruamel.yaml`). If declaring `python_dependencies`, always include both a lower floor and an upper bound (`>=X,<Y`).

---

## 6. Open Questions & Risks

1. **Local Hermes CLI Installation for Pre-PR Validation:** Since `hermes` is not currently on `PATH` on this Mac, do we already have a Hermes checkout or Desktop app installed on this machine, or should we clone `NousResearch/hermes-agent` into a sibling directory during Phase 3 to run `scripts/validate_plugin_catalog.py` and `hermes plugins validate` locally before opening the PR?
2. **Maintainer-Triggered CI Gate:** Because GitHub Actions on first-time contributor PRs to `NousResearch/hermes-agent` require a maintainer to click "Approve and run" (and catalog review is human-merged), we should open our initial catalog PR with a working, validated v1.0.0 release by **November 9th–10th** rather than waiting until November 11th.
