# Errors & Fixes — Full Session Log

Every bug found this session, in the order it was found, with the symptom,
root cause, and fix. Written for two reasons: it's a more honest record than
a changelog that only shows the final working state, and several of these
are genuinely instructive failure modes (SSE framing, nginx DNS caching,
async contextvars, race conditions) worth remembering independent of this
project.

For the load-testing-specific subset (found while stress-testing the
platform) see also [LOAD_TESTING.md](LOAD_TESTING.md#bugs-fixed-along-the-way),
which covers #7–#10 below in more depth alongside the actual load numbers.

## Summary

| # | Error | Root cause | Fix |
|---|---|---|---|
| 1 | Chat responses only appeared after a page reload | Frontend SSE parser split frames on `\n\n`; backend terminates them with `\r\n\r\n` | Normalize `\r\n`→`\n` before parsing |
| 2 | "Invalid API key" despite `.env` being correct | Docker Compose resolves `.env` relative to the *compose file's* directory, not the repo root | Always pass `--env-file <repo-root>/.env` |
| 3 | Grafana opened to the generic welcome page | No home dashboard configured | Set `GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH` |
| 4 | Grafana login rejected `admin`/`admin` | Persisted data volume had stale credentials from before fix #2 | Reset via `grafana-cli admin reset-admin-password` |
| 5 | `.env.example` missing from a fresh clone | `.gitignore`'s `.env.*` pattern also matched `.env.example` | Add `!.env.example` negation |
| 6 | Build artifacts (`*.egg-info/`) staged for commit | Not in `.gitignore` | Added `*.egg-info/` |
| 7 | Sidebar silently showed "No conversations yet" (real data existed) | nginx's static `upstream {}` block resolves the backend hostname once at startup; any chat-service restart broke the proxy until nginx itself restarted | Variable-based `proxy_pass` + Docker's embedded DNS resolver |
| 8 | ...then a `500` after fixing #7 | `set` directive placed *after* `rewrite ... break`, which halts further rewrite-phase directives — the variable was never assigned | Moved `set` before `rewrite` |
| 9 | Single chat-service instance's error rate climbed under load | One uvicorn worker = one CPU core, hard ceiling ~2,000 req/s | Horizontal scaling via the Kubernetes HPA (see LOAD_TESTING.md) |
| 10 | Kafka pod boot-looped in Kubernetes | Headless Service missing `publishNotReadyAddresses: true` — kafka-0 couldn't resolve its own DNS name until Ready, but couldn't become Ready without resolving it first | Set `publishNotReadyAddresses: true` |
| 11 | HPA never scaled back down, even fully idle | Memory *request* (256Mi) smaller than the pod's idle footprint (~210Mi) — permanently over the 80% target | Raised memory request to 384Mi |
| 12 | No per-container CPU/memory metrics in Grafana | cAdvisor can't reach the Docker daemon from inside a container on Docker Desktop for Mac | Host-side `docker stats` exporter instead |
| 13 | Chat responses showed literal `**bold**` / `1. list` syntax | No markdown rendering — raw LLM output dumped as plain text | Added `react-markdown` |
| 14 | Trailing "typing" cursor looked broken, floated on its own line | A `<span>` sibling after `ReactMarkdown`'s block-level output (`<p>`, `<li>`) can't sit inline with the last line of text | Removed it; 3-dot indicator only for the pre-first-token gap |
| 15 | `docker pull searxng/searxng:2024.9.10-...` — tag not found | Guessed a plausible-looking but nonexistent version tag | Looked up real tags, pinned to a real one |
| 16 | Web search silently never triggered — model just apologized as before | Broad error-matching (`"tool"` as a substring) caught Groq's *transient* tool-call-parsing failures (`tool_use_failed`, ~1-in-3 rate) as if the model didn't support tools at all, and gave up instead of retrying | Narrower error classification + bounded retry (succeeds within 2-3 attempts) |
| 17 | `asyncio` "Task exception was never retrieved" warnings on stream cancel | SDK's `ContextVar.reset()` can raise when a stream's `GeneratorExit` fires from a different async Context than where it was set — more likely once tool-calling made requests take longer | Wrapped resets in `try/except ValueError` |
| 18 | Assistant response and error message both vanished, screen looked blank | A delayed `GET /conversation/:id` fetch (for a brand-new conversation) could resolve *after* streaming already finished, silently overwriting local state — including a just-shown error — with an incomplete server snapshot | `trustLocalForRef` guard in `useChat.ts` |
| 19 | Web search fired inconsistently — same kind of question, sometimes searched, sometimes just refused ("I don't have real-time access") | `tool_choice="auto"` leaves the decision entirely to the model, and the system prompt gave zero guidance on when to search; smaller models (`llama-3.1-8b-instant`) are much less reliable at deciding on their own | System prompt now explicitly instructs: always search before answering anything time-sensitive |
| 20 | Fixing #19 over-corrected: a trivial unit-conversion question ("26508 ms in s") also triggered a search, taking 26.5s | New prompt said "call web_search ... even if you think you might already know the answer" — too broad, applied to timeless facts and math too | Narrowed the prompt to name what qualifies (current events, scores, prices) and explicitly exclude what doesn't (math, definitions, general knowledge); also lowered the tool-retry cap 3→2 to shrink worst-case latency |
| 21 | A bare "3+2" (or "current 3+2") right after a cricket-score question got answered as if it continued the cricket topic — one run hallucinated a fake score `360/7` | System prompt said nothing about topic continuity, so the model let the immediately preceding subject bleed into a new, unrelated, unambiguous message | Added explicit rules: judge each message on its own wording, don't assume it continues an earlier topic; a numbers/operators-only message is always math |
| 22 | Wrong match dates presented as current, and the assistant silently assumed the user was in the UK when asked "what time is it" | `SYSTEM_PROMPT` was a static string with no real "today" reference and no rule against guessing location/timezone | Converted to `_system_prompt()`, a function that injects the real UTC date every request, plus explicit instructions to never infer location/timezone and to flag date-ambiguous questions instead of guessing |
| 23 | `docker compose up --build` failed twice in a row with `pip._vendor.urllib3.exceptions.ReadTimeoutError` while installing the chat-service image | No `PIP_DEFAULT_TIMEOUT`/`PIP_RETRIES` configured; pip's default read timeout was too tight for the larger dependency set pulled in by the new JWT auth stack (`pyjwt`, `bcrypt`, `email-validator`) over a flaky connection | Set `PIP_DEFAULT_TIMEOUT=120` and `PIP_RETRIES=5` in the builder stage's `ENV` in `apps/chat-service/Dockerfile` |
| 24 | Adding a Redis job queue in front of the LLM call (for crash-survival) would have silently broken the Stop button | The old cancel path relied on `request.is_disconnected()` inside the *same* generator that called the LLM directly — once that call moved into a decoupled background worker, a client disconnect no longer touches the worker's coroutine at all, so `GeneratorExit` never reaches it | Added an explicit `chat:cancel:{request_id}` Redis flag: the HTTP handler sets it on disconnect, the worker polls it once per token, same as before — self-caught during implementation, before it ever shipped |

---

## 1. Chat responses only appeared after a page reload

**Symptom:** sending a message showed nothing happening — no streamed text,
no error — until the browser was refreshed, at which point the full
response was there.

**Root cause:** `sse-starlette` (backend) terminates every SSE event with
`\r\n\r\n`. `apps/frontend/src/lib/chatStream.ts` searched for frame
boundaries with `buffer.indexOf("\n\n")` — two consecutive `\n` never occurs
inside `\r\n\r\n` (there's a `\r` between them), so no frame boundary was
ever found. `onToken`/`onDone`/`onError` never fired. The backend persisted
the assistant's reply to Postgres regardless (persistence happens
server-side, independent of whether the client ever parsed the stream) —
so a reload, which re-fetches the conversation via REST, always showed it
correctly. That mismatch — works after reload, never live — was the tell.

**Fix:** normalize `\r\n` → `\n` on each decoded chunk before frame-splitting.

```ts
buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
```

## 2. "Invalid API key" despite the key being set correctly

**Symptom:** `GROQ_API_KEY` was set in `.env` and confirmed correct, but
chat calls failed with `GroqException - Invalid API Key`.

**Root cause:** Docker Compose resolves a bare `.env` relative to the
*compose file's* directory (`infra/docker/`), not the repository root or
the shell's current working directory. Running
`docker compose -f infra/docker/docker-compose.yml up` from the repo root
silently found no `.env` at all, so every `${GROQ_API_KEY:-}`-style
substitution resolved to empty — the container's env var was legitimately
empty, not wrong.

**Fix:** always pass `--env-file` explicitly, pointed at the real location:

```bash
docker compose -f infra/docker/docker-compose.yml --env-file .env up
```

`scripts/dev_up.py` bakes this in so it can't be forgotten.

## 3–4. Grafana defaults

**3 — generic welcome page instead of the LLM Overview dashboard:** no
home dashboard was configured. Fixed by setting
`GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH` to the dashboard's mounted
path in `infra/docker/docker-compose.yml`.

**4 — `admin`/`admin` rejected:** the Grafana data volume had already been
initialized once *before* fix #2 was in place, so its bootstrap admin
account was created against whatever `GRAFANA_PASSWORD` resolved to at that
time (effectively empty/default). Fixed with
`grafana-cli admin reset-admin-password admin` inside the running
container — a one-time fix for the already-provisioned volume, not
something that recurs on a fresh clone.

## 5–6. Git hygiene, found during a pre-commit audit

**5 — `.env.example` missing from a fresh clone:** `.gitignore` had:

```
.env
.env.*
```

`.env.*` matches any filename starting with `.env.` — including
`.env.example`, the exact file the README's Quickstart tells people to
`cp`. It was never committed. Fixed with an explicit negation:

```
.env
.env.*
!.env.example
```

**6 — `*.egg-info/` build artifacts staged:** Python packaging metadata
directories (generated by `pip install -e`) were about to be committed
alongside real source. Added `*.egg-info/` to `.gitignore` and unstaged
them.

## 7–8. The frontend silently lost the ability to list conversations

**7 — Symptom:** the sidebar showed "No conversations yet" even though
157 real conversations existed in Postgres (confirmed via direct SQL and
via `curl` straight to chat-service, both of which worked fine).

**Root cause:** `apps/frontend/nginx.conf` used a static nginx directive:

```nginx
upstream chat_service {
    server chat-service:8001;
}
```

nginx resolves a hostname in an `upstream {}` block **once**, when the
worker process starts, and caches that IP for the container's entire
lifetime. Every time chat-service got rebuilt or recreated during this
session (a new container = a new IP on the Compose network), nginx kept
proxying to the old, now-dead IP — every `/api/*` call silently 502'd,
and nothing about nginx itself needed to look unhealthy for that to happen.

**Fix:** switch to a *variable*-based `proxy_pass`, which forces nginx to
re-resolve through a real resolver on each request instead of caching at
startup:

```nginx
resolver 127.0.0.11 valid=10s;   # Docker's embedded DNS
...
location /api/ {
    set $chat_upstream http://chat-service:8001;
    proxy_pass $chat_upstream;
    ...
}
```

Verified by force-recreating chat-service and confirming the frontend kept
working without its own restart.

**8 — Symptom, immediately after the fix above:** `500 Internal Server
Error`, nginx logs: `using uninitialized "chat_upstream" variable`.

**Root cause:** the first attempt placed `set` *after* `rewrite ...
break;`. In nginx, `break` halts further processing of rewrite-phase
directives in that location block for that request — including a `set`
that appears textually after it. The variable was simply never assigned.

**Fix:** reorder so `set` runs first:

```nginx
location /api/ {
    set $chat_upstream http://chat-service:8001;   # before...
    rewrite ^/api/(.*)$ /$1 break;                  # ...the break
    proxy_pass $chat_upstream;
```

## 9–11. Found while load-testing and deploying to Kubernetes

Full methodology and numbers in [LOAD_TESTING.md](LOAD_TESTING.md); summarized here.

**9 — Single-instance error rate climbing under load:** chat-service runs
one uvicorn worker (no `--workers` flag), so it has exactly one CPU core's
throughput regardless of the host's core count — confirmed by polling
`docker stats` every second during a load test and watching chat-service
sit at a flat 100% while every other container stayed under 2%. Not a bug
so much as an un-diagnosed architectural ceiling; the fix is horizontal
scaling (the Kubernetes HPA), not more RAM or a bigger box.

**10 — Kafka pod boot loop in the `kind` cluster:**
`infra/k8s/12-kafka.yaml`'s governing headless Service didn't set
`publishNotReadyAddresses: true`. KRaft's controller-quorum-voters config
requires kafka-0 to resolve its own `kafka-0.kafka` DNS name — but a
headless Service only publishes DNS records for pods that are already
Ready, and the pod can't become Ready without first resolving that name.
Self-referential deadlock, visible as `UnknownHostException: kafka-0.kafka`
in the pod's own logs.

**11 — HPA permanently stuck at its scaled-up replica count:**
`kubectl describe hpa` showed memory utilization pinned at 82% (target
80%) with **zero load** — chat-service's idle footprint (~210Mi) was
already over the memory *request* (256Mi). Unlike CPU, per-pod memory
utilization doesn't fall as replica count rises, so this metric could
never recommend scaling down. Fixed by raising the request to 384Mi (idle
→ ~53% utilization).

## 12. No per-container CPU/memory metrics

**Symptom:** cAdvisor reported zero real containers — only a single `"/"`
root-cgroup aggregate.

**Root cause:** on Docker Desktop for Mac, the actual Docker daemon (and
therefore real cgroups/`docker.sock`) lives inside Docker Desktop's own
hidden Linux VM. cAdvisor's assumptions about reaching `docker.sock` and
reading cgroups don't hold the way they would on a native Linux Docker
host — confirmed via cAdvisor's own logs: `Cannot connect to the Docker
daemon at unix:///var/run/docker.sock`, even after explicitly bind-mounting
the socket.

**Fix:** abandoned cAdvisor for this environment; wrote
`infra/docker/docker_stats_exporter.py`, a small host-side script that
polls `docker stats` (which works fine from the host CLI, since that talks
to the real daemon through Docker Desktop's own proxying) and serves the
result as Prometheus text format, scraped via `host.docker.internal`.

## 13–14. Chat rendering

**13 — Raw `**bold**` / `1. numbered list` syntax shown literally:** the
chat UI dumped `message.content` as plain text with no markdown parsing,
even though every LLM provider writes markdown. Fixed by rendering
assistant messages through `react-markdown` with minimal custom
components (bold, lists, code blocks, links) matching the app's existing
Tailwind palette.

**14 — The streaming "cursor" looked broken, floating on its own line
below the text:** the trailing indicator was a `<span>` appended as a
sibling *after* `ReactMarkdown`'s output. Markdown renders into
block-level elements (`<p>`, `<li>`, `<h3>`, ...), and a block-level
sibling forces a line break before it — the cursor could never sit inline
with the last character of text the way it visually needed to. Rather
than fight markdown's DOM structure, removed the trailing cursor entirely:
once real tokens are landing, the growing/typewriter-revealed text is
already sufficient "still generating" feedback (this is also how
ChatGPT's own web UI behaves). The 3-dot "thinking" indicator now only
covers the genuine gap before the first token arrives.

## 15. Wrong SearXNG image tag

**Symptom:** `docker pull searxng/searxng:2024.9.10-0e0cbf1` — 
`not found`.

**Root cause:** guessed a plausible-looking version+hash tag instead of
checking Docker Hub. SearXNG's tags are date+commit-hash based and change
constantly; there was no way to guess a currently-valid one.

**Fix:** looked up the actual current tags and pinned to a real one
(`searxng/searxng:2026.7.19-6da6eee26`), consistent with this project's
"no `:latest`, pin everything" convention elsewhere in
`infra/docker/docker-compose.yml`.

## 16. Web search silently never triggered

**Symptom:** after wiring up the `web_search` tool, asking a
current-events question ("today india vs eng cricket score") still got
the same "I don't have real-time access" non-answer as before — as if the
tool had never been offered to the model at all.

**Root cause:** two layers.

First, confirmed via direct testing inside the container that the model
*was* trying to call the tool — Groq's API rejected it:

```
"code":"tool_use_failed","failed_generation":"<function=web_search {...}>"
```

This is a known Groq/open-weight-model flakiness: the model's raw tool-call
generation doesn't always parse cleanly on Groq's server, independent of
whether tool calling is supported at all. Retrying the identical request a
few times reliably got a clean parse (confirmed empirically: attempt 1 and
2 failed, attempt 3 succeeded, repeatably).

Second — and this is what actually caused the silent fallback — the
original error classifier was too broad:

```python
_TOOL_UNSUPPORTED_MARKERS = ("tool", "function calling", "function_call")
```

The substring `"tool"` matches `"tool_use_failed"` too, so this *transient,
worth-retrying* error was being classified the same as "this model
fundamentally doesn't support tools," and the code gave up and fell back
to a plain completion on the very first failure — silently, with no retry.

**Fix:** split into two distinct marker sets — a narrow one for genuine
transient parse failures (`"tool_use_failed"`) that triggers a bounded
retry (`parallel_tool_calls=False` also helps, per Groq's own guidance),
and a separate, more specific set for actual "unsupported" messages that
skip straight to the plain-completion fallback. Applied identically to
both the streaming and non-streaming paths in
`apps/chat-service/app/services/llm_client.py`.

## 17. `asyncio` "Task exception was never retrieved" on stream cancellation

**Symptom:** background warnings in chat-service logs after a stream got
cut short:

```
ValueError: <Token var=<ContextVar name='obs_session_id' ...>> was created in a different Context
```

**Root cause:** `observation_context()` in
`packages/sdk/llm_obs_sdk/context.py` is a synchronous `@contextmanager`
wrapping an async generator body (`chat_service.stream()`). When a client
disconnects, Python delivers `GeneratorExit` to unwind the generator — but
that can happen from a different asyncio `Context` than the one the
`ContextVar.set()` calls originally ran in, and `.reset()` requires the
exact same Context that produced the token. This is a known sharp edge
where contextvars meet async generators + SSE frameworks; it existed
before this session's changes but became easy to trigger once tool-calling
made individual requests take noticeably longer (more time in-flight = more
opportunity for a disconnect to land mid-generator).

**Fix:** the Context being torn down is being discarded either way, so
there's nothing to leak by skipping a reset that structurally can't apply.
Wrapped each reset in `try/except ValueError: pass` rather than attempting
a deeper architectural fix (e.g. converting to `@asynccontextmanager` end
to end) that wasn't warranted for what is, in practice, harmless cleanup
noise.

## 18. Response and error both vanished after a failed/slow request

**Symptom:** on a brand-new conversation, if the LLM call failed fast
(e.g. a Groq rate-limit-flavored timeout) or was simply slow, the screen
would end up showing *nothing* — no error banner, no empty assistant
bubble, composer re-enabled as if nothing had ever been sent. The
conversation was in the sidebar, but felt like a dead end.

**Root cause:** a race in `useChat.ts`'s reset-on-conversation-change
effect. Sending on a new chat navigates to the newly-created conversation
id, which enables a `GET /conversation/:id` React Query fetch. The
existing guard only protected against that fetch resolving *while
`streaming` was still true*:

```ts
useEffect(() => {
  if (streaming) return;
  setMessages(initialMessages);
  setError(null);
  ...
}, [conversationId, initialMessages]);
```

But that fetch can just as easily resolve *after* streaming already
flipped to `false` — a fast failure or a slow request both create this
window. For a brand-new conversation, the server-side snapshot at that
point is often incomplete (if the LLM call failed before any tokens
streamed, `chat_service.py` never persists an assistant row at all — see
its `if text:` guard). When that stale/incomplete `initialMessages`
landed, the effect fired again — now unguarded — and overwrote the local
state wholesale: the error message the user had just seen, and the empty
assistant bubble marking that a response was attempted, both disappeared.

**Fix:** track which conversation id local state should currently take
precedence over a background refetch for, set at the moment a send starts
(or a new conversation id becomes known), and cleared only once the user
genuinely navigates elsewhere:

```ts
const trustLocalForRef = useRef<string | null>(null);

useEffect(() => {
  if (streaming) return;
  if (conversationId !== null && conversationId === trustLocalForRef.current) return;
  trustLocalForRef.current = null;
  setMessages(initialMessages);
  ...
}, [conversationId, initialMessages]);
```

Set in `send()` for existing conversations, and in the `onStart` SSE
handler for newly-created ones. Verified by reproducing the original race
(a request that fails within ~1s of a brand-new conversation being
created) and confirming the error banner now survives.

## 19. Web search fired inconsistently

**Symptom:** the exact same *kind* of current-events question behaved
differently between messages. Checked the database directly for two
back-to-back examples on the default model (`groq/llama-3.1-8b-instant`):

| Message | Prompt tokens | What happened |
|---|---|---|
| "spain vs argentina who won" | 527 | Tool fired; answered "based on the search results," though the results themselves didn't contain a final score |
| "india vs eng score" | 199, one single API call | Tool never fired at all — flat "I don't have real-time access" |

Token count is the tell: a tool round trip appends search results to the
follow-up call, so a message that actually searched has a visibly larger
prompt than one that didn't.

**Root cause:** `tool_choice="auto"` (in
`apps/chat-service/app/services/llm_client.py`) leaves the decision to
search entirely up to the model's own judgment — and the system prompt
gave it nothing to judge by:

```python
SYSTEM_PROMPT = "You are a helpful, concise assistant."
```

Smaller models are markedly less reliable at inferring on their own that
"today's score" requires a lookup rather than a training-data answer;
`llama-3.3-70b-versatile` (used in most of the manual testing during this
session) called the tool consistently, but the app's actual *default*
model, `llama-3.1-8b-instant`, did not.

**Fix:** made tool-use policy explicit rather than emergent
(`apps/chat-service/app/services/chat_service.py`):

```python
SYSTEM_PROMPT = (
    "You are a helpful, concise assistant. You have a web_search tool. "
    "Your training data has a cutoff date and cannot include anything after "
    "it — scores, prices, schedules, news, releases, or any other fact that "
    "changes over time. For any question like that, call web_search before "
    "answering, even if you think you might already know the answer; never "
    "tell the user you lack real-time access without having tried "
    "searching first. If the search results don't contain what's needed, "
    "say so plainly rather than guessing."
)
```

Re-tested the identical failing case on the identical small model — the
tool now fires (prompt tokens 199 → 1216) and, when the search results
still don't contain a live score, the model says so explicitly instead of
either refusing outright or guessing:

> "Based on the search results, I was unable to find the current score
> between India and England. However, I found information about the match
> schedule..."

**Known remaining limitation, not a bug:** general web search (SearXNG,
self-hosted, no API key) indexes news articles and schedule pages, not a
live scoreboard feed. For a question like "current score," the actual
number is often genuinely not sitting in any indexed page's text at query
time — no amount of prompt tuning fixes that; only a dedicated
paid/rate-limited sports-data API would, which is a different tradeoff
than the self-hosted, zero-account approach this project chose. The fix
above makes the failure mode honest ("couldn't find it") instead of
silent (never tried) or fabricated (hallucinated a number) — that's the
realistic ceiling for this architecture.

## 20. Fixing #19 over-corrected: everything started searching

**Symptom:** immediately after the #19 fix, a completely unrelated
follow-up message — literally converting `26508 ms in s` — also triggered
a web search ("Based on the search results, converting 26508
milliseconds..."), and the whole exchange took 26.5 seconds for what
should be instant arithmetic.

**Root cause:** the #19 fix's wording was too broad:

> "call web_search before answering, **even if you think you might
> already know the answer**"

That phrase doesn't distinguish "the answer could be stale" (true for
scores, prices, news) from "the answer is fixed forever" (true for math,
unit conversions, definitions) — the model applied it uniformly to both.
Every extra unnecessary search call adds a full SearXNG round trip
(~3s observed) plus a second LLM completion, so this wasn't just wasteful,
it was a real latency regression for the common case.

**Fix:** rewrote the prompt to name what qualifies rather than describe a
vague threshold, and explicitly enumerate what doesn't:

```python
SYSTEM_PROMPT = (
    "You are a helpful, concise assistant. You have a web_search tool — use "
    "it only for things that can change in the real world after your "
    "training cutoff: live scores, prices, schedules, news, releases, or "
    "similar current-events facts, especially when the question says "
    "'today', 'latest', 'current', or names a specific recent date. Never "
    "tell the user you lack real-time access without having searched "
    "first for that kind of question. "
    "Do NOT search for math, unit conversions, definitions, general "
    "knowledge, coding help, or anything else you can already answer "
    "correctly and completely on your own — searching for those only adds "
    "delay for no benefit. "
    "If search results don't contain what's needed, say so plainly rather "
    "than guessing."
)
```

Also lowered `_TOOL_CALL_MAX_ATTEMPTS` from 3 to 2 in
`apps/chat-service/app/services/llm_client.py` — each retry on a
`tool_use_failed` parse error is a full extra round trip to the provider,
so this shrinks the worst case for whenever a search genuinely is needed,
independent of the prompt fix.

**Verified:** re-tested both cases back-to-back on the same small model.
Math conversion: 2.7s, no search, direct arithmetic answer. A genuine
current-events question ("latest news about spacex starship") right
after it: 1.9s, tool fired correctly, answer grounded in real search
results. Both markedly faster than the 26.5s outlier, and the two cases
are now correctly distinguished rather than one policy applied to both.

## 21. Earlier conversation topic bled into an unrelated new message

Sent a cricket-score question, then in the same conversation sent a bare
`3+2` (and separately, `current 3+2`). Instead of answering the math, the
model treated it as a follow-up about the cricket match — one run went
as far as hallucinating a fake score, `360/7`, that had never appeared in
any real search result.

**Root cause:** the system prompt had no instruction about topic
continuity one way or the other, so the model defaulted to treating the
newest message as a continuation of whatever the conversation was already
about — reasonable behavior for genuine follow-ups ("what about tomorrow's
match?"), wrong for a message that is unambiguous on its own.

**Fix:** added explicit rules to the system prompt: judge each message on
its own wording rather than assuming it continues an earlier topic, and
treat a message that's only numbers/operators as always being math,
regardless of what came before it.

**Verified:** re-ran the exact failing sequence (cricket question, then
`3+2`) — no hallucinated score, correct final answer of `5`. Note: the
literal phrase "current 3+2" still triggered an unnecessary (though no
longer harmful) search on this small model — a known, acknowledged
remaining imperfection rather than a regression.

## 22. Wrong match dates presented as current + silently assumed UK time zone

Asked a cricket-score question, then in the same conversation asked "what
time is it" — the assistant answered as if the user were in the UK,
without ever asking, and separately presented stale match dates as if
they were current.

**Root cause:** `SYSTEM_PROMPT` was a plain static string — no grounded
reference to the actual current date, and no rule against inferring a
user's location or time zone from unrelated context (an earlier mention
of England in a cricket question is not a location disclosure).

**Fix:** changed `SYSTEM_PROMPT` from a constant into a `_system_prompt()`
function that injects the real UTC date (`datetime.now(timezone.utc)`) on
every request, plus explicit rules: never guess the user's location or
time zone, ask instead; if a date is ambiguous, say so rather than
presenting a guess as fact; and check search-result dates against the
real "today" before treating them as current.

**Verified:** reproduced the exact original scenario via direct `curl`
(cricket question, then a time question, same conversation) — the
assistant now asks a clarifying question about the match-date ambiguity,
and for the time question defaults to neutral UTC while asking for the
user's time zone instead of assuming one.

## 23. Docker build failed with a pip `ReadTimeoutError`

`docker compose up --build chat-service frontend` failed twice in a row,
both times with an identical stack trace at the same step:

```
pip._vendor.urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool(host='files.pythonhosted.org', port=443): Read timed out.
target chat-service: failed to solve: process "/bin/sh -c pip install ./packages/shared[db] ./packages/sdk ./apps/chat-service" did not complete successfully: exit code: 2
```

**Root cause:** the JWT auth work added three new dependencies
(`pyjwt`, `bcrypt`, `email-validator`) to `apps/chat-service/pyproject.toml`.
The Dockerfile's builder stage had no `PIP_DEFAULT_TIMEOUT` or
`PIP_RETRIES` configured, so pip used its default (fairly tight) read
timeout per chunk — enough margin normally, but not always enough for the
larger install pulling extra wheels over an occasionally slow connection.

**Fix:** added to the builder stage's `ENV` in
`apps/chat-service/Dockerfile`:

```dockerfile
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5
```

**Verified:** rebuild succeeded; went on to verify the entire JWT auth
flow end-to-end (register, cookie issuance, `/auth/me`, refresh rotating
all three cookies, CSRF-protected `POST /chat`, logout, wrong-password
rejection, duplicate-email rejection) via `curl`, then confirmed the
login/register pages, route guarding, and the 2-minute auto-refresh timer
all work correctly in a real browser session.
