# Technical notes

Development log and protocol notes kept from the original project. See the main [README](../README.md) for an overview.


A Windows PySide6 chat client using the **unofficial** [DeepSeek4Free](https://github.com/xtekky/deepseek4free) private web API, not DeepSeek's official API. The protocol can change without notice. Authenticated session creation and one streaming request were verified on 19 November 2026. The private protocol can still change. Since 20 November 2026 the app can optionally use the unofficial Qwen Chat web API (chat.qwen.ai) instead; see *Qwen provider* below. DeepSeek remains the default.

## Run

On Windows 10/11, run `dist\DeepSeekDesktop-Stable\DeepSeekDesktop-Stable.exe` from the complete distribution folder. For source, install Python 3.11 or later, run `py -m pip install -r requirements.txt`, then `py main.py`. Build with `build.bat`; copy the entire `dist\DeepSeekDesktop-Stable` folder, not just the executable. The bundled WASM solver is from the upstream project; its MIT license is in `dsk/LICENSE`.

On first launch, Settings asks for a web session token, never a password. Sign in at https://chat.deepseek.com in your own browser, inspect the site's local storage, and copy the `value` of `userToken` if available. Token storage uses Windows Credential Manager. Remove it using Settings. Your messages are saved without encryption in `%LOCALAPPDATA%\DeepSeekDesktop\history.sqlite3`; exports are plaintext. Treat the token and local history as private.

New chat creates a local conversation; a remote session is created when you send. Enter sends and Shift+Enter adds a newline. Select a conversation to view history; use Settings to change defaults and token, and Export to save the selected chat. Select text to copy it, or copy the last message. Retry last resends a user message when no assistant message was saved. Stop requests cancellation; a blocked network operation may take up to the configured timeout before it stops.

## Compatibility and limitations

- The upstream repository pins `curl-cffi==0.8.1b9`; that source distribution failed to build here because its referenced Windows library download returned 404. This project uses a newer curl-cffi release, which has not been verified against the live private API.
- The adapter recognizes the observed current session response and SSE fragment format as well as the older upstream format. It records response message IDs when present. Private API changes can still break multi-turn context. Unexpected or empty responses are reported as errors rather than invented answers.
- A browser Cloudflare challenge may prevent use. Sign in and complete any verification manually on the official website; this app does not automate challenges or import clearance cookies. Completing verification in a browser may not make this client work.
- Network calls run in a worker; cancellation cannot interrupt a blocked request immediately. No automatic retries are performed, avoiding accidental duplicate generation and respecting rate limits. Retry is manual. Retry-After is not currently displayed.
- Markdown is rendered using Qt's Markdown renderer. Dedicated syntax highlighting and per-code-block copy buttons are not implemented; select code and use Copy selected / last. Regeneration of an already completed response is not implemented.
- Exports contain messages for the selected conversation, not a complete history archive. No connection status check is performed on saved tokens.

## Tests

Run `py -m pytest -q`. Tests mock HTTP and cover startup/Markdown, SQLite restart, session creation and streaming, cancellation before a request, and rate-limit reporting. A live session and streaming test passed with a temporary user-supplied token. Never put tokens in source code, logs, or test fixtures. Diagnostic logs contain only HTTP status, content type, and allowlisted JSON field shapes at `%LOCALAPPDATA%\DeepSeekDesktop\diagnostics.log`.


## Multi-turn fix (19 November 2026)

The current DeepSeek stream exposes a numeric `response_message_id`. SQLite stores the remote ID as text, and the former adapter sent that text back as `parent_message_id`; a live two-turn probe reproduced HTTP 422 with that request. The adapter now converts only decimal remote IDs back to integers for follow-up requests, preserving the same remote chat session. An 11-test suite includes three consecutive turns with a database restart and verifies the outgoing IDs are `null`, then numeric IDs. The server's 422 response in the probe was non-JSON `application/octet-stream`, so its exact validation message could not be read. A successful live three-turn chat was not tested because further live testing was declined. The EXE was rebuilt, but multi-turn success should be confirmed with a fresh credential.


## Persian interface

The interface is right-to-left in Persian with a light blue default theme. Existing installations switch to this theme once; the optional dark theme remains available in Settings. Markdown fenced code blocks (three backticks) and inline code (one backtick) each show a «کپی کد» link that copies only that code. The complete `dist\DeepSeekDesktop-Stable` folder is required to run the EXE.

## Response continuation

When the Web stream reports `INCOMPLETE`, the app sends `POST /api/v0/chat/continue` with the same `chat_session_id`, numeric remote `message_id`, and `fallback_to_resume: true`. Auto Continue is on by default and stops after three retries with 1, 2, and 3 second waits. The app appends only new text and stores an incomplete message ID for the manual «ادامهٔ پاسخ» button, including after a restart. Manual cancellation and normal `FINISHED` responses are not continued. The endpoint and payload were confirmed against an authenticated request: continuing a completed test reply returned HTTP 200 with business code 22, as expected for a completed reply. A genuinely incomplete live reply was not available to test, so successful live continuation is not claimed.

## Reliability and performance update

The application now commits a user message with `pending` status before network work starts. The network worker uses its own SQLite connection, marks the user `sent` only after receiving a remote response message ID, saves assistant output about every 100 ms, and commits final or interrupted status. On startup, unfinished `pending` and `streaming` records become `interrupted`; their content remains visible. Existing databases are backed up to `history.pre-status.bak` before the status-column migration. Conversation pages load 50 messages at a time, and streaming updates append new text to the visible chat around every 75 ms. Markdown is rebuilt when loading a page or finishing a response, not for each token. Diagnostics are available from the sidebar and include sanitized request and persistence metadata, Qt event-loop stalls, and Windows working-set memory.

An authenticated probe on 19 November 2026 showed a completed desktop chat in both DeepSeek's `history_messages` response and the first page of `chat_session/fetch_page`. Local `pending` or `failed` messages are not evidence of remote persistence. Website display can lag or differ from these API results. Tests cover 500 messages, long code, network interruption, failed requests, abrupt process termination, recovery, and database migration. A real Windows reboot was not performed.

## Qwen provider (chat.qwen.ai, unofficial)

Added 20 November 2026. Open **تنظیمات** (Settings), choose **سرویس گفت‌وگو → Qwen (chat.qwen.ai)**, paste the Qwen token into **توکن نشست وب Qwen**, pick a model in **مدل Qwen**, and press **ذخیره**. The top bar shows the active service and model. To change the token later, paste a new one and save; to delete it, tick **حذف توکن Qwen ذخیره‌شده** and save. Leaving the field empty keeps the saved token. The Qwen token is stored in Windows Credential Manager as service `DeepSeekDesktop`, user `qwen-web-session`. It is kept separately from the DeepSeek token, which is still stored under `web-session`. **بررسی توکن Qwen و دریافت فهرست مدل‌ها** makes two read-only requests, `GET /api/v1/auths/` and `GET /api/models`, then fills the model list.

**How to get the token:** sign in at https://chat.qwen.ai in your own browser. Press F12 and open Application (Chrome/Edge) or Storage (Firefox). Under Local Storage → `https://chat.qwen.ai`, copy the **value** of the key `token`. It is a long JWT that starts with `eyJ`. Surrounding quotes and a `Bearer ` prefix are removed automatically. Do not enter your password, and never share the token.

How it works: the first message in a chat calls `POST /api/v2/chats/new` and stores the returned chat id as the conversation's remote session. Each message is sent to `POST /api/v2/chat/completions?chat_id=…` with `stream: true`, `incremental_output: true`, and `version: "2.1"`. The phase-based SSE stream is parsed into thinking (`think` / `thinking_summary`) and answer text. The `response_id` from `response.created` is saved as the next turn's `parent_id`, so Qwen keeps the multi-turn context on its server. The تفکر and جست‌وجوی وب checkboxes map to Qwen's `thinking_enabled` and `auto_search` settings.

A conversation stays with the service it started with. Switching the service in Settings affects new chats and chats that have not been sent yet. Cleared chats use the newly selected service.

Limitations, verified 20 November 2026:
- **Region block:** from unsupported regions, `chat.qwen.ai/api/*` returns HTTP 405 with "Qwen is not available in your region". The app shows this as a clear error. The built-in browser follows the Windows system network/proxy settings; the app itself does not configure proxies.
- **Alibaba WAF (baxia):** from a non-blocked server, POST requests to the `/api/v2/` endpoints without browser anti-bot signatures (`bx-ua`, WAF cookies) returned an Aliyun slider-captcha HTML page. This app sends only the bearer token. It does **not** solve captchas, generate anti-bot signatures, or import browser cookies. If the WAF challenges the request, the app reports "web firewall / captcha" and stops, so Qwen may be unusable with this client even with a valid token. This could not be tested with a real logged-in token.
- No automatic retries. Responses that are rate-limited (HTTP 429, `RateLimited`) or rejected are reported, and answers are never invented. "Continue response" uses `/chat/continue` for DeepSeek. For Qwen it sends a follow-up prompt in the same chat (see below).
- The private protocol, required SPA `version` header (`0.3.26`), and model ids (live anonymous list: `qwen3.7-plus`, `qwen3.8-max`) can change without notice. If the default model stops working, refresh the model list in Settings.
- Diagnostics log only endpoint paths without chat ids, HTTP status, content type, and allowlisted JSON field names. Tokens, prompts, and answers are never logged.

Tests: `tests/test_qwen.py` mocks HTTP. It covers chat creation, SSE parsing (thinking and answer), three-turn `parent_id` chaining across a database restart, 401/429/`RateLimited`/WAF/region/HTML/5xx errors, stream errors, empty streams, cancellation, the no-retry policy, token-free logs, the provider database migration, Worker routing, separate Credential Manager entries, and per-chat provider binding.

## Qwen via the built-in browser (default for Qwen since 20 November 2026)

The direct HTTP client was blocked by Alibaba's WAF slider captcha even with a valid token, so Qwen now uses an **embedded browser** (QtWebEngine) by default. The user logs in and completes any captcha **manually** in that window. The app never solves captchas, never generates `bx-ua` or other anti-bot signatures, and never reads, copies, or exports cookies. Each API request (`/api/v2/chats/new`, `/api/v2/chat/completions`, `/api/models`, `/api/v1/auths/`) runs as `window.fetch(..., {credentials: 'include'})` **inside the chat.qwen.ai page**, so the site's own cookies and scripts apply. The page's own `localStorage.token` is used as the Bearer token, and that value never leaves the page. The SSE body is read with a `ReadableStream` reader. Python polls the collected text with `runJavaScript`, and no QWebChannel object is exposed to the site's scripts. Stop aborts the in-page fetch with `AbortController`. QtWebEngine stays on the GUI thread, and the network Worker exchanges requests and events with it through a thread-safe queue. Parsing, multi-turn `parent_id` handling, and error mapping are shared with the HTTP transport in `app/backend/qwen_protocol.py`.

Steps in the app:
1. Open **تنظیمات** and set **سرویس گفت‌وگو** to **Qwen (chat.qwen.ai)**. **روش اتصال Qwen** should be **مرورگر داخلی (پیشنهادی)**, which is the default.
2. Click **ورود / تأیید Qwen در مرورگر داخلی**. In the window that opens, sign in to chat.qwen.ai yourself and complete any verification or captcha, then click **ادامه**.
3. Optionally click **بررسی اتصال Qwen و دریافت فهرست مدل‌ها**, choose **مدل Qwen**, and click **ذخیره**. Then send messages as usual.
4. If Qwen later asks for verification or login, or reports `401`, a WAF captcha page, `RGV587`/`FAIL_SYS_USER_VALIDATE`, no token, or no response before the timeout, the same browser window opens with a Persian explanation. Complete the step and click **ادامه**. The app then asks whether to resend your last message, a one-click manual retry. Nothing is retried automatically.

The browser profile is persistent. Cookies, localStorage, and cache live in `%LOCALAPPDATA%\DeepSeekDesktop\qwen-web`, so the login survives restarts. Delete that folder to sign out completely. **توکن Qwen (اختیاری)** is now an optional manual override that is used instead of the page token. **HTTP مستقیم با توکن** keeps the old token-only client as a fallback. The browser follows the Windows system proxy, so a VPN that sets the system proxy also covers it. The direct HTTP fallback does not use the system proxy, so it needs a system-wide (TUN) VPN. Without a VPN, from Iran, chat.qwen.ai shows "Qwen is not available in your region", and the app reports that clearly. The user agent is Chromium's own without the `QtWebEngine/x` token. Pop-up logins such as OAuth open in separate windows of the same profile. The diagnostic `DeepSeekDesktop-Stable.exe --qwen-browser-smoke <file.json>` loads chat.qwen.ai, saves a screenshot next to the JSON file, and reports whether a login token is present, as true or false only.

Tests: `tests/test_qwen_browser.py` uses a scripted bridge to cover the request spec without tokens or cookies, chunk reassembly, multi-turn, error-to-verification mapping, timeout, cancel and abort, and Worker routing. It also runs `tests/webengine_bridge_check.py`, which is **real QtWebEngine** in a subprocess against a local fake Qwen server. That check verifies cookies are sent, the Bearer token comes from page localStorage, the split SSE stream, two turns, WAF/expired/no-token detection, and that Stop really aborts the server connection. A real logged-in chat.qwen.ai conversation has not been tested.

## Qwen "log in again" loop fix (20 November 2026)

Symptom: logged in inside the built-in browser (chatting on the page works), yet every message from the app
reported an invalid/expired session and re-opened the login window.

Root cause (verified live with a copy of the browser profile): a Qwen token that had been saved in Settings
earlier was sent as a *manual override* instead of the page's own token. Qwen web tokens are JWTs that
live only ~15 minutes (the site refreshes them itself through `auth.qwen.ai/api/v2/auths/refresh`), so the
saved one had expired; `POST /api/v2/chats/new` answered HTTP 200 with
`{"success":false,"data":{"code":"unauthorized","details":"Token has expired, please log in again."}}`.
The same request with the page's token succeeded.

Fixes:
- The built-in browser transport always uses the page's fresh `localStorage` token; a manual token is only a
  fallback when the page has none, and an expired manual token is ignored (logged as `manual_token_ignored`).
  The direct-HTTP transport refuses an expired token up front with a clear message.
- If the page token itself is (about to be) expired, the bridge reloads chat.qwen.ai once so the site
  refreshes it, waits up to ~10 s for a fresh token, then sends the request.
- The error mapper only treats genuine auth codes/messages (`unauthorized`, `401`, "token has expired", ...)
  as "log in again"; the old substring matches on `login`/`limit` are gone. Every error now carries the
  server's own code and message (`[Qwen server: code: details]`), which the Persian messages show as
  «پاسخ سرور: …».
- diagnostics.log now records status, content type, the first 300 characters of non-SSE error bodies
  (JWTs, bearer tokens, cookies, e-mails and long opaque strings redacted), the token source
  (`page`/`manual`) and which mapper branch fired. Token values, cookies and message text are never logged.
- Settings warns when the saved Qwen token has expired.

## Modern interface (20 November 2026)

- Bundled **Vazirmatn** font (`app/assets/fonts`, SIL Open Font License 1.1, see `OFL.txt`).
- Light and dark themes (QSS, toggle in the sidebar footer or in Settings → ظاهر), RTL layout.
- Chat bubbles with Markdown (tables, lists, bold, links) and Pygments-highlighted code blocks; every code
  block has a «کپی کد» link and inline code copies on click.
- Sidebar with search, conversation list and a «گفت‌وگوی جدید» button; bundled SVG line icons.
- Auto-growing message box with send/stop buttons and thinking / web-search chips.
- Header pill to switch provider and Qwen model, plus a live status indicator while streaming.
- Errors appear as toasts (with a one-click «تلاش دوباره»); the Qwen login/verification window is unchanged.
- Settings is organised in tabs: سرویس‌ها / ظاهر / گفت‌وگو / درباره.
- `DeepSeekDesktop-Stable.exe --ui-preview out.png [Light|Dark]` renders the window with sample messages
  (temporary database) and saves a screenshot.

## Qwen inline code, tool phases, streaming render (20 November 2026)

- **Code stays in the chat.** By default (Settings → گفت‌وگو → «Qwen: کد کامل داخل چت (بدون ابزار)»), Qwen requests turn off the code interpreter, function calling, and plugins (`feature_config.code_interpreter=false`, `function_calling=false`, `plugins_enabled=false`, plugins stay on only when web search is on). A short instruction is also placed before your message. It asks the model to write all code as complete fenced Markdown blocks in the reply, without tools and without omitting parts. Turn the option off to send your message unchanged. These flags come from open-source Qwen web clients. They were not checked against a live request, because the app was running and a second session could rotate the login cookie.
- **Tool phases are no longer dropped.** If Qwen still uses a tool, the phases `tool_call`/`function_call`/`code_interpreter`/`tool_result`/`role:function` are collected. They then appear in the answer as «ابزار Qwen: …» with the tool's code in a fenced block, any HTML string inside that code as its own `html` block, and the tool output as a `text` block. Unknown phase names are logged as `qwen stream unknown_phase=<name>`, with the name only and never any content. The stream summary logs `finish_reason`, the tool count, and the phase names.
- **«ادامهٔ پاسخ» for Qwen.** If a reply is cut off (`finish_reason=length`) or interrupted after Qwen accepted the message, the button sends a follow-up in the same chat, using `parent_id` = the cut-off reply. The follow-up asks Qwen to continue exactly where it stopped, without repeating, and to keep writing inside the same code block. It runs only when you click the button.
- **Incremental Markdown while streaming.** Streamed text is rendered in place every 90 ms, with no full re-render. Finished paragraphs become Markdown once. An opening ``` fence becomes a real code block at once (LTR, monospaced, highlighted, with a «کپی کد» link that copies the code received so far). Each finished code line is appended as it arrives, and only the current partial line or paragraph is redrawn. The block is closed automatically while the fence is still open. Code blocks use one paragraph per line, with no tables, because Qt re-lays out a whole table on every change, so a 3,000-line block streams at constant cost. The finished message is rendered from the database with the same styles. Assistant replies now sit in the document flow (no table bubble). Each paragraph gets `dir` rtl or ltr from its first strong character. Copying a selection drops the code-line padding.
- **Rendering on Windows.** The chat document uses `PreferNoHinting` and a 14 px document margin, to address the clipped first character in RTL bubbles. Only one full render runs when a reply finishes (it was two).
- **Stale token after a reload.** When the page token is about to expire, the bridge reloads the page once. It then waits until the token has changed and an extra 2.5 s have passed before sending. This uses a short token fingerprint kept in the page's own `sessionStorage`. A request sent right after the refresh was seen to get `401 Unauthorized`.
- Preview: `python main.py --ui-preview-stream <prefix> [Light|Dark]` simulates a 2,500-line streamed HTML reply, with a temporary database and no network. It saves `<prefix>_early.png`, `<prefix>_mid.png`, `<prefix>_final.png`, and `<prefix>_stats.json`.
- **coder.qwen.ai** is Qwen's agentic coding workspace. It runs tasks in a cloud sandbox with GitHub branches and PRs. It is not a chat-completion API, so it is not integrated. For code, use chat.qwen.ai with inline-code mode, for example with the `qwen3-coder-plus` model.

## Project mode «حالت پروژه» (21 November 2026)

The model can propose file creations, edits and deletions in a folder you choose. Nothing is written until you click.

- **Setup:** header button **پروژه** → **انتخاب پوشه پروژه**. The folder is saved per conversation (new DB columns `project_root`, `project_mode`, `project_files`; existing data unchanged). **حالت پروژه برای این گفت‌وگو** turns it on or off for that chat.
- **Files tab «فایل‌ها»:** the project tree respects `.gitignore` and skips `node_modules`, `.git`, `venv`/`.venv`, `dist`, `build`, `__pycache__`, binaries and symlinks. Tick files, or write `@name` / `@path` in your message, to send their content. Limits: at most 400 KB per file, attachments capped at 60,000 characters, about 150,000 characters of context in total. The budget line turns red when you go over.
- **What is sent:** a protocol instruction, a compact project tree, the attached files, then your text. Your own text is what is stored and shown. This works for both Qwen and DeepSeek.
- **Edit formats the model must use:** ```` ```file:path ```` (complete new content), ```` ```edit:path ```` with aider-style `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` pairs, and ```` ```delete:path ````. Four backticks are used when the content contains ``` itself.
- **Tab «تغییرات پیشنهادی»:**
  - While a reply streams, progress is shown. After it, one entry appears per file with a syntax-highlighted, left-to-right diff (unified view, or **کنار هم** for side by side).
  - Buttons per file: **اعمال** / **رد**, plus **اعمال همه**.
  - A SEARCH block must match exactly once. If not, a whitespace-tolerant line match is tried, and it must also be unique; an ambiguous or missing match is never applied. **درخواست اصلاح از مدل** prepares a correction request in the message box.
  - After applying: **باز کردن در ویرایشگر** and **باز کردن پوشه**.
- **Safety:**
  - Paths must stay inside the project root: absolute paths, `..`, `.git/` and symlink escapes are rejected.
  - Before writing, the app re-checks that each file still matches what the plan was built against.
  - A delete needs a confirmation.
  - Writes are atomic.
  - UTF-8 encoding, BOM and CRLF/LF line endings are preserved.
  - Originals are backed up to `%LOCALAPPDATA%\DeepSeekDesktop\project-history\<project-hash>\<timestamp>\` before writing. **بازگردانی آخرین تغییرات** restores the last apply.
- **Qwen greeting fix:** the Qwen inline-code note now applies only when the answer needs code ("If and only if…; for greetings and normal conversation answer normally, without any code"). Tools stay disabled.
- **Preview:** `python main.py --ui-preview-project <prefix>` uses a temporary folder and database.

## Project agent tools «ابزارهای عامل» (21 November 2026)

In project mode the model can now ask the app to run tools. It writes a block such as
```` ```tool:read_file ```` with JSON arguments. The app runs the tool and sends the results back automatically as the next message, until the model gives a final answer (at most 10 tool rounds per request).

| Tool | What it does | Approval |
|---|---|---|
| `list_dir` | folder structure (skips .git, node_modules, … and .gitignore) | automatic |
| `find_files` | find files by glob (`**/*.png`) | automatic |
| `search` | grep inside text files (text or regex) | automatic |
| `read_file` | read a text file with line numbers / line range | automatic |
| `image_info` | image format, width × height, size (PNG/JPEG/GIF/WebP/BMP/ICO/SVG) | automatic |
| `http_request` | test an API (method, headers, JSON body); redirects are not followed, cookies hidden | automatic for localhost, otherwise «اجرا» |
| `download_file` | download into the project folder only (no overwrite unless asked) | always «اجرا» |
| `run_command` | PowerShell (or `"shell": "cmd"`) in the project folder, timeout 120 s, output limited to 20k chars | always «اجرا» (optional session toggle for read-only commands) |

* All paths stay inside the project folder (absolute paths, `..`, symlinks and `.git` are rejected).
* Each tool round is shown in the chat as cards: «نمایش خروجی/بستن», «✔ اجرا» / «✖ رد» for approvals, «■ توقف (Kill)» while a command runs. The Stop button stops the whole loop.
* The panel checkboxes «ابزارهای عامل (خواندن، جست‌وجو، ترمینال، وب)» and «اجرای خودکار فرمان‌های فقط‌خواندنی در این نشست» turn tools on/off (saved) and allow read-only commands (this session only).
* Images are not uploaded to the model; only their metadata is sent.
* Greetings and normal chat do not trigger tools; the instruction tells the model to use them only when needed.

## Structured edit tools «ابزارهای ویرایش» (21 November 2026)

To avoid retyping code, the model refers to locations and the app does the mechanical work. Every edit becomes a proposal in «تغییرات پیشنهادی» (diff → «اعمال» → backup → undo). Proposals are batched: all edits of one agent loop form one review list.

* `move_lines` / `copy_lines`: a file plus a line range (`start`/`end`, optionally checked by `start_marker`/`end_marker`), copied or moved to a file (created if missing) at `position` start/end, `to_line`, `after` or `before` a unique line. Optional `indent` (+n / -n / "auto"). If the line numbers are stale, the markers relocate them; a mismatch is an error, not a guess.
* `delete_lines`, `replace_lines` (range plus short new text), `insert_text`, `insert_file_content`.
* `replace_text`: literal or regex (`$1` groups) in one `path` or a `glob`, with `expected_count` / `max_count` safeguards and `dry_run` counts.
* `move_path` / `rename_path` (files or folders, emptied folders removed), `copy_path` (binary files too), `make_dir`. Import/require/include references are updated best effort: JS/TS (relative, extension-less, `/index`), CSS/SCSS (`@import`, `url()`), HTML (`src`/`href`), PHP (`require`/`include`, `__DIR__`), C/C++ `#include "…"`, Python absolute imports, Java `package`/`import`, Go import paths (whole package folders). C# namespaces are not path based.
* `apply_patch`: a unified diff (git or plain; tolerant of line offsets and trailing whitespace, ambiguous hunks rejected).
* `count_lines` runs automatically like the other look-up tools. `read_file` shows the *proposed* version of files that have pending changes.
* Text keeps its UTF-8 BOM and CRLF/LF style; a new file created from moved lines inherits the source's style.
* When a reply only contains successful edit tools, no extra model turn is spent: the user just reviews the diff. Failed edits are reported back to the model automatically.
