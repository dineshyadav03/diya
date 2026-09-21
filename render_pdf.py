"""Source of the Truffle research dossier's content, and the script that builds the PDF.

    python render_pdf.py     ->  Truffle_Research_Dossier.pdf   (GENERATED: edit this file, never the PDF)

The rendering helpers and styles are in build_pdf.py. truffle-research.html is an older, hand-written
web version of the same text; it is not generated from here and can lag behind this file.
"""
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak, HRFlowable
)
from reportlab.platypus.tableofcontents import TableOfContents
from build_pdf import (
    styles, md, esc_amp, P, render_bullets, render_table, render_callout,
    render_code, render_timeline, render_namegrid, render_pills, render_facts,
    PAGE_W, PAGE_H, MARGIN, INK, DIM, FAINT, BORDER, LED, ACCENT
)

CW = 6.35 * inch  # usable content width

# ============================================================= CONTENT =====

SECTIONS = []

def sec(num, sid, title, intro=None):
    s = {'num': num, 'id': sid, 'title': title, 'intro': intro, 'blocks': []}
    SECTIONS.append(s)
    return s

# ---- 1. What Truffle Is ----------------------------------------------------
s = sec(1, 'vision', 'What Truffle Is', 'The one-paragraph version, before the detail.')
s['blocks'] += [
    ('p', '**Truffle** is a consumer hardware device -- called **Truffle1** -- plus a companion '
          'software ecosystem, built by a small Los Angeles company operating as **Deepshard, Inc.** '
          'The pitch is a personal computer whose entire job is to run a large language model and a '
          'growing set of "apps" (tools) for you, physically in your home, so that your prompts, files, '
          'and behavioural data never have to leave the device to reach a cloud model.'),
    ('p', 'The marketing language for this is an **"exo-cortex"**: an external, always-on extension of '
          'your own mind that runs locally, gets to know your habits over time, and -- critically to how '
          'the company frames it -- belongs to you rather than a hyperscaler\'s data centre. The homepage '
          'copy is unusually blunt about the political framing: _"Beyond the confines of corporate '
          'controlled Intelligence, Truffle1 emerges as the antithesis, the anti-hero, and a private, '
          'local exo-cortex, conceived as a remedy to cloud dependency, recurring costs, and centralized '
          'control."_'),
    ('p', 'In practice this cashes out as three things bundled together:'),
    ('ul', [
        '**A box** -- a small, low-power inference computer built around an NVIDIA Jetson module, with '
        'visible status LEDs, that sits on a shelf like a router.',
        '**A client** -- desktop app ("Symphony") and iOS app ("Radiance") that let you talk to the '
        'device, install "apps," schedule automations, and manage memory/permissions.',
        '**An SDK** -- a Python framework (now called **Truffile**) that lets developers write new '
        'tools/integrations the on-device agent can call, and deploy them straight to the hardware.',
    ]),
    ('p', 'This report treats all three layers, but leans hardest on the third, since that\'s where the '
          'actual AI-engineering decisions -- model choice, tool-calling protocol, sandboxing, '
          'proactive-agent design -- are visible and documented.'),
]

# ---- 2. Naming Collisions ---------------------------------------------------
s = sec(2, 'naming', 'Naming Collisions -- Read This First',
        '"Truffle" is an unusually overloaded name in the AI/dev-tools space right now. Four unrelated '
        'companies use it. This report is about exactly one of them.')
s['blocks'] += [
    ('namegrid', [
        ('OK', 'Truffle (truffle.net / itsalltruffles.com) -- this report',
         'Deepshard, Inc., Los Angeles. Makes the Truffle1 hardware "exo-cortex" and the Truffile SDK. '
         'GitHub org: `deepshard`. X: `@itsalltruffles`.', True),
        ('X', 'Truffle Security (trufflesecurity.com)',
         'Unrelated cybersecurity company, maker of the open-source secret-scanner **TruffleHog**. Raised '
         'a $25M Series B in November 2025 led by Intel Capital and a16z.', False),
        ('X', 'Truffle AI (YC Winter 2025, Bengaluru)',
         'Unrelated agent-infrastructure startup founded by Shaunak Srivastava and Rahul Karajgikar. '
         'Sells APIs for deploying AI agents without managing infra. Raised $500K seed in March 2025.', False),
        ('X', 'Truffle (hiretruffle.com)',
         'Unrelated recruiting/HR content company; CEO Sean Griffith.', False),
    ]),
    ('p_dim', 'Search results for "Truffle" + "AI" mix all four freely -- most funding and team searches '
              'surface the wrong company. Everything else in this report is cross-checked against '
              '`truffle.net`, `docs.truffle.net`, and the `github.com/deepshard` organisation specifically.'),
]

# ---- 3. Company & History ---------------------------------------------------
s = sec(3, 'company', 'Company &amp; History')
s['blocks'] += [
    ('facts', [
        ('Legal entity', 'Deepshard, Inc.'), ('Trades as', 'Truffle'),
        ('HQ', 'Los Angeles, CA'), ('GitHub org', '`github.com/deepshard`'),
        ('Seed funding', '$1.78M (Jul 2022)'), ('Investors', 'Accelerate Fund, Sprout Fund'),
        ('Public launch', 'March 2024'), ('Community', '`discord.gg/itsalltruffles`'),
    ]),
    ('p', 'Deepshard raised a modest $1.78M seed round in July 2022, well before the current wave of '
          'AI-hardware attention, then spent roughly 18 months building before a March 2024 public '
          'preorder launch as "Truffle-1." The GitHub organisation\'s stated mission is a single line: '
          '_"We\'re building a personal AI computer."_'),
    ('callout_warn', 'Unusually anonymous team',
     'Deepshard has been consistently opaque about who runs it. At the 2024 launch, no founder names '
     'appeared anywhere on the marketing site, which Hacker News commenters flagged directly as a '
     'credibility problem for a company asking for $500 deposits. The clearest public thread back to a '
     'real name is a LinkedIn profile for an **Aidan Guarniere**, listed as affiliated with "Deepshard, '
     'Inc." in Los Angeles -- not confirmed as a founder or CEO. Support contacts that do appear in the '
     'docs and GitHub issues (a first-name address and a generic contact address at the company domain) are first-name-only. The '
     'company\'s root domain, `itsalltruffles.com`, redirects to a page that is literally just ASCII art '
     'and the tagline "Stream of consciousness" -- the anonymity looks deliberate, part of the brand\'s '
     'off-grid/anti-corporate posture, rather than accidental.'),
    ('p', 'Whatever the reason, the low profile hasn\'t stopped the product from shipping and iterating: '
          'the public docs changelog runs in weekly-ish increments from April through at least '
          '**August 29, 2026** at the time of writing, which is a materially different picture from the '
          'render-heavy preorder page HN was skeptical of in 2024 (see Section 8).'),
]

# ---- 4. Hardware -------------------------------------------------------------
s = sec(4, 'hardware', 'Hardware -- Truffle1',
        'The physical device is not custom silicon -- it\'s a productized NVIDIA Jetson developer module '
        'with Truffle\'s own enclosure, firmware, and always-on software stack on top.')
s['blocks'] += [
    ('table', ['Spec', 'Value'], [
        ['Compute module', 'MONO:NVIDIA Jetson AGX Orin, 64GB unified memory'],
        ['Claimed AI performance', 'MONO:~275 TOPS (INT8)'],
        ['Memory bandwidth', 'MONO:~200 GB/s'],
        ['Power draw', 'MONO:~60 W'],
        ['Max model size (on-device)', 'MONO:up to ~100B parameters (quantized)'],
        ['Launch benchmark: Mixtral 8x7B', 'MONO:~22 tok/s'],
        ['Launch benchmark: Mistral 7B', 'MONO:~50 tok/s'],
        ['Connectivity', 'MONO:Wi-Fi, Bluetooth LE, USB-C'],
        ['Deployment model', 'Home server appliance -- always on, discovered on the LAN by the '
                              '`truffile scan` CLI / Symphony onboarding'],
        ['Launch price', 'MONO:$1,299 (with a $500 refundable preorder deposit in 2024)'],
    ], [2.1 * inch, 4.25 * inch]),
    ('p', 'A dedicated `docs.truffle.net/hardware/overview` page exists but was marked "coming soon" as '
          'of this research pass -- notable, since every software surface (SDK, client, release notes) '
          'has thorough docs. That gap, plus the release notes\' silence on any hardware revision, '
          'suggests the currently-shipping unit is still the original Orin-based board rather than a '
          'refresh onto NVIDIA\'s newer Jetson Thor (Blackwell) line, which only reached general '
          'availability in mid/late 2026.'),
    ('p', 'The enclosure carries programmable status LEDs that the on-device agent can control directly '
          '-- the August 2026 release notes describe prompting the agent in natural language to build a '
          'scheduled "dim the LEDs 8pm-6am" routine, and to re-theme the LED behaviour "Tron-like" by '
          'having it read and rewrite its own LED-control skill file. Even a physical, ambient feature of '
          'the hardware is exposed as something the agent can reprogram, not just a fixed firmware '
          'setting.'),
]

# ---- 5. Software Stack --------------------------------------------------------
s = sec(5, 'software', 'Software Stack', 'Four named surfaces, each with a distinct job.')
s['blocks'] += [
    ('namegrid', [
        ('', 'Symphony',
         'Desktop client (Windows, macOS Intel + Apple Silicon, Linux). Handles device onboarding/pairing, '
         'memory & custom-instruction settings, app installs and OAuth flows, and -- as of Aug 2026 -- a '
         'system-tray quick-actions menu for schedules, LEDs, and remote access.', False),
        ('', 'Radiance',
         'iOS companion app. Full visual redesign across mid-2026 releases: Home/Lock-screen widgets, '
         'voice input, redesigned search/schedules/settings, direct in-app app-store installs.', False),
        ('', 'Conductor',
         'A lighter-weight control surface reachable from Symphony\'s tray menu alongside Convo and the '
         'full app -- a quick dashboard rather than a separate product.', False),
        ('', 'Convo',
         'The actual agent conversation backend. Stateful, thread-based (a fixed "Main" thread plus '
         'arbitrary side threads), and fully scriptable from the CLI with JSON output and exit codes. '
         'Replaced an older Chat/Task-ID system in a one-way, non-migrated cutover on August 10, 2026.', False),
    ]),
    ('h3', 'The App Store'),
    ('p', 'Around Convo sits an app store of first- and third-party integrations the agent can call or be '
          'extended with. Examples that shipped through 2026 release notes include Slack, Gmail '
          '(multi-account), Notion, Obsidian, WHOOP (wearable health data), Home Assistant, Exa search, '
          'Alpha Vantage (market data), Internet Archive / Wayback Machine / Project Gutenberg, X, '
          'Firecrawl, Higgsfield (image/video generation), Pinterest, Viator (travel), and a "Daily News" '
          'digest app. As of August 29, 2026, apps also support **multiple accounts per app** (e.g. two '
          'Slack workspaces, a personal and work Gmail) and a **per-connection permission model** -- Read '
          'only, Read and write, or Auto review -- that governs how much autonomy the agent gets with that '
          'specific account.'),
]

# ---- 6. AI Engineering --------------------------------------------------------
s = sec(6, 'ai', 'AI Engineering -- How It\'s Actually Built',
        'This is the part worth reading closely. Truffle\'s AI-engineering story is really the story of '
        'three successive SDKs converging on a standard protocol (MCP), wrapped around a small, swappable '
        'local model and a genuinely proactive agent loop.')
s['blocks'] += [
    ('h2', '6.1 &middot; Model lineage -- what\'s actually running'),
    ('p', 'Truffle doesn\'t train its own foundation model. Its engineering work is in _serving, routing '
          'to, and building tools around_ open-weight models on constrained edge hardware, and in '
          'swapping the underlying model as better small models ship.'),
    ('table', ['Period', 'On-device model(s)', 'Cloud-assist path'], [
        ['Mar 2024 launch', 'Mixtral 8x7B (~22 tok/s), Mistral 7B (~50 tok/s)', '--'],
        ['~2025 (SDK docs)', 'Gemma3-27B / Qwen-32B / Qwen-14B, selectable by task weight', 'DeepSeek R1 for heavier reasoning'],
        ['Apr 19, 2026', 'Upgraded to **Qwen 3.6** -- shipped for better agentic tool-use', '--'],
        ['May 11, 2026', 'Added a dedicated local embeddings model for long-term memory; larger context', '--'],
    ], [1.1 * inch, 3.6 * inch, 1.65 * inch]),
    ('p', 'Two things stand out. First, the model is explicitly a replaceable component -- the release '
          'notes treat a model swap ("Qwen 3.6 now runs on your Truffle!") the same way a SaaS product '
          'would announce a backend upgrade, with the device even printing a screenshot of itself '
          'identifying as Qwen 3.6 when asked. Second, the earlier SDK generation described an optional '
          'cloud fallback (DeepSeek R1) for tasks the local model couldn\'t handle well -- a pragmatic '
          'hybrid stance that sits in some tension with the "fully local, no cloud" marketing, though the '
          'newer 2026 docs no longer mention a cloud model explicitly.'),
    ('h3', 'Routing: a mixture-of-models classifier'),
    ('p', 'The original 2024 SDK documentation describes the core dispatch mechanism plainly: every app '
          'declares a `Goal` string in its metadata, and this goal is _"presented to the core '
          'mixture-of-models almost as a system prompt."_ App selection isn\'t a hand-written intent '
          'classifier -- it\'s another LLM call (or set of calls) that reads the user\'s prompt against '
          'every installed app\'s declared purpose, then routes to the best match. Each app\'s '
          '`description` field also seeds _"synthetic data for live classification,"_ implying the '
          'routing layer is calibrated per-app rather than pure zero-shot matching.'),

    ('h2', '6.2 &middot; Inference API -- OpenAI-compatible, on your LAN'),
    ('p', 'Every Truffle exposes a local, OpenAI-Chat-Completions-compatible REST surface at '
          '`/if2/v1/*` ("IF2" -- inference-facing v2). This is the same shape as calling '
          '`api.openai.com`, just pointed at a device on your home network -- a deliberate compatibility '
          'choice that lets any existing OpenAI-SDK client, LangChain integration, or curl script work '
          'against the device with only a base-URL change.'),
    ('code', 'List available models', 'curl -sS http://<device-host>/if2/v1/models | python -m json.tool'),
    ('code', 'Chat completion (non-streaming)',
     'curl -sS http://<device-host>/if2/v1/chat/completions \\\n'
     '  -H "Content-Type: application/json" \\\n'
     '  -d \'{\n'
     '    "model": "<model-id-or-uuid>",\n'
     '    "messages": [\n'
     '      {"role": "user", "content": "Give me one sentence about Truffle."}\n'
     '    ]\n'
     '  }\''),
    ('p', 'The request schema supports the features of a modern serving stack, not a toy demo: `stream` '
          '(SSE, terminated by `data: [DONE]`, with an `include_usage` option for token accounting), '
          '`temperature` / `top_p`, `max_tokens`, a `reasoning: {"enabled": true}` flag that surfaces the '
          'model\'s chain-of-thought as a separate field, and full `tools` / `tool_choice` support in '
          'OpenAI\'s function-calling format. Vision input uses an `image_url` content block with a '
          'base64 data URI, natively supporting JPEG/PNG/BMP, with other formats transcoded through '
          'Pillow if installed.'),
    ('p', 'Streaming events carry incremental `content`, `reasoning`, and `tool_calls` deltas '
          'independently, which is what lets the CLI\'s `truffile infer` REPL render a live "thinking" '
          'trace, a token-per-second readout (`tokens [142/580/722] | decode 48.2 t/s | ttft 312ms`), and '
          'streamed tool-call indicators all at once.'),

    ('h2', '6.3 &middot; Agent architecture -- Convo, memory, and proactivity'),
    ('p', '**Convo** is the layer above raw inference: a stateful, multi-threaded agent session per user, '
          'with a fixed `Main` thread (id `0`) and any number of ad-hoc side threads. It is deliberately '
          'built to be scriptable, not just chatted with through a UI -- the CLI accepts one-shot prompts '
          'with explicit thread targeting and returns machine-readable JSON with a defined contract:'),
    ('code', 'truffile convo -- one-shot automation contract',
     '{\n  "task_id": "123",\n  "thread_id": "123",\n  "backend": "convo",\n  "title": "QA debug",\n'
     '  "device": "truffle-6272",\n  "content": "...",\n  "thinking": null,\n  "tool_calls": null,\n'
     '  "pending_user_response": false,\n  "status": "ok",\n  "error": null,\n  "interrupted": false,\n'
     '  "timed_out": false\n}'),
    ('p', 'Exit codes are equally deliberate: `0` success, `1` runtime/auth error, `2` bad input, `3` '
          '"needs a human in a supported client," `75` "the completion fence was lost -- do not blindly '
          'retry," `124` timeout, `130` interrupted. Designing explicit, distinguishable exit codes -- '
          'especially the `75`/"don\'t auto-retry" case -- is a small but real sign of engineering '
          'maturity: the kind of thing you only add after being burned by naive automation double-sending '
          'requests.'),
    ('h3', 'Memory and personalization ("Dreaming")'),
    ('p', 'The marketing site describes a nightly "dreaming" cycle -- _"moving beyond interactions to '
          'consolidation and reflection, constructing a \'you world.\'"_ The engineering reality, per the '
          '2026 release notes, is more concrete: a locally-run embeddings model (added May 2026) backs a '
          'searchable, taggable memory store, with a distinguished "User profile" memory category the '
          'model is told to weight heavily, plus user-editable "Custom instructions" -- a local '
          'vector-memory system plus a system-prompt layer, both exposed and editable through Symphony '
          'rather than hidden.'),
    ('h3', 'Proactivity -- the agent acts without being asked'),
    ('p', 'The most distinctive architectural piece is how _background_ apps feed a separate '
          'proactive-agent loop. A background app doesn\'t return a chat response -- it periodically calls '
          '`submit_text(content=..., uris=..., priority=...)` with a natural-language description of '
          'something that changed. The proactive agent ingests these submissions across every installed '
          'app at once and decides whether to act, notify, or stay quiet.'),
    ('callout_warn', 'Documented cross-app side effect',
     '_"Background context can trigger action in any app, not just yours. If an Instagram message about '
     'an Amazon order lands in the proactive agent\'s context, Truffle might use your Amazon app to add '
     'the item to cart."_ That\'s a direct, disclosed consequence of pooling all background context into '
     'one proactive decision-maker -- app developers are explicitly told to write context submissions '
     'with that in mind, and the August 2026 read-only / read-write / auto-review permission tiers read '
     'as the product-level mitigation for exactly this risk.'),

    ('h2', '6.4 &middot; Tool-use -- from custom protobufs to native MCP'),
    ('p', 'This is where the SDK\'s history is most visible, because Truffle rebuilt its own tool-calling '
          'protocol twice, converging on the industry-standard one.'),
    ('h3', 'Generation 1 (2024) -- the original `truffle` SDK'),
    ('p', 'The first public SDK described apps as _"a toolbox in a sandbox"_: a Python class, decorated '
          'per-method with `@truffle.tool(...)` and `@truffle.args(...)`, running inside an **ephemeral '
          'Ubuntu ARM container** with dependencies auto-installed. Under the hood, the SDK parsed each '
          'tool\'s type-annotated signature and auto-generated a gRPC server plus Protobuf '
          'request/response messages for it at runtime -- a deliberately language-agnostic design '
          '(Python first, but meant to make binding other languages easy later). State lived in ordinary '
          'instance attributes and was transparently serialized/restored between sessions.'),
    ('h3', 'Generation 2 (2025) -- `hyphae`'),
    ('p', 'An intermediate SDK, `hyphae`, kept the decorator model but added **predicate-gated tools** -- '
          'a tool can declare `predicate=lambda self: self.has_paper_selected()` so it\'s only offered to '
          'the model once relevant state exists. It also introduced a Docker-style `Truffile` container '
          'manifest and a `hyphae build / connect / upload` CLI workflow, plus a documented pattern for '
          'one app delegating work to another model entirely.'),
    ('h3', 'Generation 3 (2026, current) -- `truffile` and native MCP'),
    ('p', 'The current SDK, confusingly also spelled **Truffile**, drops the custom gRPC-per-tool '
          'machinery for foreground tools in favour of the **Model Context Protocol (MCP)** -- the open '
          'standard for exposing tools to LLM agents. A foreground app now subclasses `ForegroundApp`, '
          'serves MCP over **streamable HTTP** (not `stdio`), and registers tools with a `ToolSpec` object '
          'whose fields map directly onto MCP tool metadata. Background apps keep a lighter-weight, '
          'Truffle-specific runtime (`BackgroundWorkerApp`) for scheduling and context submission, but can '
          'reach into their own foreground\'s MCP tools via `ctx.connect_foreground()`.'),
    ('p', 'Adopting MCP is a meaningful engineering decision, not just a rename: any Truffle foreground '
          'app is, structurally, a standard MCP server -- and the reverse also works, since `truffile '
          'infer --mcp <url>` lets a developer point the on-device model at any external MCP server for '
          'local testing. Truffle apps and, say, an Anthropic-ecosystem MCP server are now interchangeable '
          'at the protocol level.'),
    ('h3', 'Runtime discipline'),
    ('p', 'The docs are unusually candid about a specific operational failure mode: apps that don\'t close '
          'their own HTTP/DB/subprocess handles on exit. Both the foreground and background app guides '
          'independently call this out as **"the #1 cause of flaky redeploys and container runtime '
          'crashes,"** and every bundled example app wires an `atexit` cleanup handler.'),

    ('h2', '6.5 &middot; Developer workflow'),
    ('p', 'The CLI-first loop is consistent across all three SDK generations, and in the current one '
          'looks like this:'),
    ('code', 'The Truffile developer loop',
     'pip install truffile\n\n'
     'truffile scan                          # discover Truffle devices on the LAN\n'
     'truffile connect truffle-6272 --user-id "$TRUFFLE_USER_ID"\n\n'
     'truffile create my-app --path ./apps   # scaffold truffile.yaml + fg/bg stubs\n'
     'truffile validate ./apps/my-app        # lint config + parse Python for syntax errors\n'
     'truffile deploy --dry-run ./apps/my-app\n'
     'truffile deploy ./apps/my-app          # upload, run install steps, register\n\n'
     'truffile infer --mcp http://127.0.0.1:8000/mcp   # test the app\'s MCP server locally, pre-deploy\n'
     'truffile convo --new --json --quiet --timeout 60 "Summarize my installed apps"'),
    ('h3', 'Minimal working app (current SDK)'),
    ('p', 'A complete foreground app -- one callable tool, wired for MCP, with proper cleanup -- from '
          'Truffle\'s own docs:'),
    ('code', 'my_app_foreground.py',
     'from truffile.app_runtime import ForegroundApp, ToolSpec, err\n'
     'from mcp.types import CallToolResult, TextContent\n'
     'import atexit, httpx\n\n'
     'class MyApp(ForegroundApp):\n'
     '    def __init__(self) -> None:\n'
     '        super().__init__("myapp", logger_name="myapp.foreground")\n'
     '        self._http = httpx.AsyncClient(timeout=30.0)\n'
     '        self._register_tools()\n\n'
     '    def _register_tools(self) -> None:\n'
     '        @self.tool(ToolSpec(\n'
     '            name="search_web",\n'
     '            description="Search the web and return the top results. "\n'
     '                         "Use this when the user asks about current events.",\n'
     '            icon="magnifying-glass",\n'
     '            annotations={"readOnlyHint": True, "destructiveHint": False},\n'
     '        ))\n'
     '        async def search_web(query: str, limit: int = 5):\n'
     '            if not query.strip():\n'
     '                return err("query is required")\n'
     '            response = await self._http.get(\n'
     '                "https://api.example.com/search", params={"q": query, "n": limit}\n'
     '            )\n'
     '            results = response.json().get("results", [])[:limit]\n'
     '            text = "\\n".join(f"- {r[\'title\']} -- {r[\'url\']}" for r in results)\n'
     '            return CallToolResult(content=[TextContent(type="text", text=text)])\n\n'
     '    async def aclose(self) -> None:\n'
     '        await self._http.aclose()\n\n'
     'app = MyApp()\n'
     'atexit.register(lambda: __import__("asyncio").run(app.aclose()))\n\n'
     'if __name__ == "__main__":\n'
     '    app.run()'),
    ('p', 'Note what\'s absent: no gRPC stub generation, no protobuf schema file, no separate manifest '
          'describing the tool\'s arguments -- the function\'s own Python type hints _are_ the MCP input '
          'schema, and the docstring/description is what the router uses to decide when to call it. A '
          'direct simplification versus Generation 1\'s explicit protobuf-generation step.'),
    ('h3', 'An AI-native piece of documentation'),
    ('p', 'The SDK\'s install page ships a ready-to-paste prompt block explicitly designed to be fed to '
          '**Claude Code, Codex, or another coding agent**, instructing that agent to set up the whole '
          'Python environment, install Truffile, run `truffile load all` to pull down bundled `SKILL.md` '
          'files, and read those skills before writing any code. Truffle ships onboarding material written '
          '_for an AI agent to execute_, not just for a human to read.'),
    ('h3', 'Emergent capability: agents that write their own tools'),
    ('p', 'The June 26, 2026 release introduced **RunToolScript**: the on-device agent can write a new '
          'tool from a natural-language request and save it for reuse, rather than the developer '
          'pre-registering every possible action. The shipped examples are genuinely agentic -- "make a '
          'tool where every time there\'s a GitHub PR assigned to me, message me in my personal DM on '
          'Slack" produces a persistent, schedulable automation, generated and installed by the model '
          'itself.'),

    ('h2', '6.6 &middot; Agent Registry Protocol -- a Web3 side-quest'),
    ('p', 'One repository in the `deepshard` GitHub org, **AgentRegistry**, describes something the '
          'shipped consumer product doesn\'t currently expose: a decentralized, EVM/Solidity-based '
          '_"AppStore for agents,"_ where Truffle devices themselves are the trust anchor.'),
    ('ul', [
        '**Hardware attestation** -- a `HardwareAttestation.sol` contract verifies a device\'s serial '
        'number against a Merkle root signed by the hardware manufacturer\'s root key.',
        '**Sybil resistance via TEE** -- this attestation is tied to the Jetson Orin\'s **OP-TEE** '
        '(a Trusted Execution Environment), so one physical device can\'t cheaply masquerade as many '
        'agents.',
        '**Staking &amp; a native token** -- an `AgentRegistry.sol` contract handles discovery and '
        'requires economic stake from registered agents; a `SomeNativeToken.sol` contract provides the '
        'staking/payment asset.',
        '**Off-chain execution** -- only discovery, identity, and rules live on-chain; actual '
        'agent-to-agent interaction and settlement are designed to happen off-chain for scalability.',
    ]),
    ('p', 'Read alongside the AI-engineering material above, this is best understood as Truffle\'s answer '
          'to "how do autonomous agents pay and verify each other" -- using owned, attested hardware as a '
          'substitute for identity/reputation systems a centralized marketplace would normally provide. '
          'It has not shipped in Symphony, Radiance, or the Truffile SDK as of this research pass, and '
          'should be read as exploratory rather than product.'),
]

# ---- 7. Release Timeline -------------------------------------------------------
s = sec(7, 'timeline', 'Release Timeline',
        'Selected highlights from launch to the most recent public changelog '
        '(`docs.truffle.net/release-notes`), skewed toward AI/agent-relevant changes.')
s['blocks'] += [
    ('timeline', [
        ('March 2024', 'Public launch as "Truffle-1"',
         '$1,299 preorder ($500 deposit), Jetson AGX Orin 64GB, Mixtral 8x7B at ~22 tok/s. '
         'Decorator-based Python SDK ("toolbox in a sandbox") with gRPC/Protobuf auto-generated per tool.'),
        ('2025', '`hyphae` SDK generation',
         'Predicate-gated tools, Docker-style app containers, on-device models shift to Gemma3-27B / '
         'Qwen-32B / Qwen-14B, with an optional DeepSeek R1 cloud-assist path.'),
        ('Apr 19, 2026', 'Qwen 3.6 becomes the on-device model',
         'Pitched as an agentic-tool-use upgrade. Same release adds Obsidian, vision/image upload in '
         'Convo, and previews Radiance for iOS.'),
        ('May 11, 2026', 'Local embeddings model, larger context, mid-turn steering',
         'Long-term memory gets a real local embeddings backbone; queue/steer mid-response; password + '
         'recovery-code login added.'),
        ('Jun 26, 2026', 'RunToolScript -- self-authored tools',
         'The agent can write and persist its own tools from natural-language requests. LED control '
         'exposed to the agent. Convo gets soft/hard reset commands.'),
        ('Jul 4 - Aug 1, 2026', 'App Store expansion, proactivity push, Radiance ships on iOS',
         'Alpha Vantage, Internet Archive, Daily News, X, Firecrawl apps added. "Truffle takes more '
         'initiative" release; iOS widgets; install apps directly through conversation.'),
        ('Aug 10, 2026', 'Convo replaces the legacy Chat/Task backend',
         'One-way, non-migrated cutover to the current thread-based agent model; scriptable one-shot '
         'mode with JSON contracts and defined exit codes ships alongside it.'),
        ('Aug 29, 2026', 'Multi-account apps + granular tool permissions (latest at research time)',
         'Multiple accounts per app; per-connection Read-only / Read-write / Auto-review permission '
         'tiers -- the direct product-level response to cross-app proactive-agent risk.'),
    ]),
]

# ---- 8. Reception & Criticism ---------------------------------------------------
s = sec(8, 'reception', 'Reception &amp; Criticism',
        'The 2024 launch drew real skepticism on Hacker News and X. Much of it reads differently with '
        'two-plus years of shipped changelog behind it -- but it\'s useful context for anyone evaluating '
        'the product today.')
s['blocks'] += [
    ('h3', 'What critics said at launch (HN thread on Truffle-1, March 2024)'),
    ('ul', [
        '**"It\'s just a Jetson with a markup."** The core hardware is a stock NVIDIA Jetson AGX Orin dev '
        'module, and buying the board directly plus writing your own inference stack would cost $300-400 '
        'less than the $1,299 asking price.',
        '**Closed compiler on an "open" pitch.** Truffle stated its compiler/middleware was proprietary '
        'and "wouldn\'t be valuable to open source anyway" -- unconvincing given the open-source-model '
        'narrative (Mixtral, Mistral) otherwise.',
        '**Naming collision on install.** `brew install truffle` collided with an unrelated, '
        'already-established Ethereum development tool of the same name on Homebrew.',
        '**No named leadership, mostly renders.** At launch the site had no founder names and the '
        'product existed "almost exclusively" as renders rather than demoed hardware -- a real red flag '
        'for several commenters given money was being collected up front.',
    ]),
    ('h3', 'A counter-voice'),
    ('p', 'Not everyone was skeptical. Indie-hacker/tech commentator **Pieter Levels (@levelsio)** '
          'publicly praised the launch specifically for its lack of hype, contrasting it with the Humane '
          'AI Pin\'s polished-but-empty marketing: paraphrased, his take was that Truffle openly described '
          'itself as "a wrapper for an Nvidia chip" whose software made it meaningfully better -- not '
          'claiming to be the best value, but at least being honest about what it was.'),
    ('h3', 'Where things stand now'),
    ('p', 'The most concrete answer to the 2024 skepticism is simply that the product kept shipping: a '
          'weekly-cadence public changelog through August 2026, a real (if still small-team) app '
          'ecosystem, a native iOS app, and a tool-calling layer that converged on an actual industry '
          'standard (MCP) rather than staying a proprietary dead end. That doesn\'t resolve the anonymity '
          'question, and no major outlet appears to have published an independent hands-on review of a '
          'shipped unit -- but "vaporware" is a harder label to apply to something with two and a half '
          'years of dated, specific release notes than it was to a preorder page of renders.'),
]

# ---- 9. Competitive Landscape ------------------------------------------------------
s = sec(9, 'landscape', 'Competitive Landscape')
s['blocks'] += [
    ('table', ['Product', 'Model location', 'Business model', 'How Truffle differs'], [
        ['Rabbit R1 / Humane AI Pin', 'Cloud', 'Hardware + often a subscription',
         'Truffle inverts both axes: inference is local by design, and there\'s no subscription implied '
         'by the public materials.'],
        ['ChatGPT / Claude / Gemini apps', 'Cloud', 'Subscription',
         'No dedicated hardware, no on-device data residency, no home-automation-style "app" ecosystem '
         'tied to physical device presence.'],
        ['DIY local LLM box (llama.cpp/Ollama)', 'Local', 'One-time hardware cost',
         'Truffle adds the parts a DIY box doesn\'t have out of the box: a polished client, a maintained '
         'app store, a proactive agent loop, MCP-native tool SDK, OTA updates.'],
        ['Home automation hubs (Home Assistant)', 'Local/hybrid', 'One-time or open-source',
         'Truffle treats these as one integration among many rather than being a home-automation product '
         'itself.'],
    ], [1.55 * inch, 0.75 * inch, 1.3 * inch, 2.75 * inch]),
    ('p', 'The most defensible positioning is for a specific audience: privacy-conscious power users and '
          'developers who want a real device to build personal agent tooling against -- one with actual '
          'file-system/API access to their own accounts -- rather than a sandboxed cloud assistant. The '
          'MCP-native SDK in particular means skills built for Truffle and skills built for other '
          'MCP-compatible agent runtimes are largely portable, which lowers the cost of betting on the '
          'platform as a developer.'),
]

# ---- 10. Build vs. Buy -----------------------------------------------------------
s = sec(10, 'buildbuy', 'Build vs. Buy',
        '"Just buy the Jetson yourself" is the obvious objection to a $1,299 appliance built on '
        'off-the-shelf NVIDIA hardware. As of September 2026 that objection is weaker than it sounds -- '
        'and in one specific case it has actually inverted. Figures below are current-as-of-research '
        'prices, independently re-checked against live listings and vendor pages.')
s['blocks'] += [
    ('callout_warn', 'The one everyone assumes, and gets wrong',
     'NVIDIA raised Jetson-line prices by up to 101% on July 21-22, 2026, citing industry-wide memory '
     'costs. The bare **Jetson AGX Orin 64GB Developer Kit** -- the exact module inside a Truffle -- '
     'moved from a $1,999 launch price to **$3,499 on NVIDIA\'s own marketplace** (live-confirmed; a '
     'third-party reseller SKU shows $2,999, Amazon $3,299). Add a required NVMe SSD (2026 NAND-shortage '
     'pricing puts a 1TB drive at $130-200) and a from-scratch DIY build on the identical silicon now '
     'runs **~$3,300-3,700** -- roughly 2.5-3x a complete Truffle, before writing a single line of the '
     'agent/memory/tool-ecosystem software Truffle ships with.'),
    ('h2', '10.1 &middot; Building it yourself'),
    ('table', ['Path', 'Upfront cost (Sep 2026)', 'Setup effort', 'The catch'], [
        ['Bare Jetson AGX Orin 64GB + llama.cpp/Ollama', 'MONO:~$3,300-3,700',
         'Medium-high -- flash JetPack from a separate host, add storage, fight ARM/CUDA build errors',
         'Same chip as Truffle, but now costs more than Truffle post price-hike, and ships with none of '
         'the app ecosystem, mobile client, or proactive agent'],
        ['Mac mini / Mac Studio (Apple Silicon)', 'MONO:$2,899-$5,399+',
         'Low for basic chat, high to replicate proactivity/remote access',
         '2-4x the price for a much faster general-purpose machine; hyped 2026 M5 Max benchmarks are '
         'pre-launch marketing -- real 70B throughput is likely 8-15 tok/s, not the 25-32 tok/s circulating'],
        ['Budget/used PC + consumer GPU (RTX 3090/4060 Ti/5070)', 'MONO:~$1,000-1,700',
         'High -- drivers, systemd services, your own remote-access tunnel',
         'The one DIY path that can still undercut Truffle, but Ollama still has no native MCP support '
         '-- every tool integration needs a bridge you build yourself'],
        ['Open-source kit (Home Assistant + Ollama/Open WebUI)', 'MONO:$260-330 (weak) - $1,700-2,400 (capable)',
         'High -- no single installer; every layer is a separate project',
         'Cheapest entry point, but Home Assistant\'s own docs describe its AI layer as reactive, not '
         'autonomous -- nothing here replicates Truffle\'s proactive agent'],
    ], [1.75 * inch, 1.15 * inch, 1.55 * inch, 1.9 * inch]),
    ('p', 'The pattern across all four DIY paths is the same: raw model-serving capability is achievable, '
          'often at competitive or better tokens/sec once you\'re not bandwidth-bound by the Jetson\'s '
          '~200GB/s memory. What none of them replicate without real engineering effort is the packaged '
          'part of the product -- a mobile app, a stateful multi-thread agent, an OAuth-managed app '
          'store, and above all a proactive background agent, which every option above either lacks '
          'entirely or explicitly disclaims.'),

    ('h2', '10.2 &middot; Buying a different device instead'),
    ('p', 'Three other "personal AI hardware" gadgets get compared to Truffle by default, and none of '
          'them compete on the same axis -- all three are fully cloud-dependent, the opposite of '
          'Truffle\'s core pitch.'),
    ('table', ['Device', 'Price', '2026 status'], [
        ['Rabbit R1', 'MONO:$199, no subscription',
         'Still sold and updated, but reputation never recovered from a 2024 investigation alleging its '
         '"Large Action Model" was largely GPT-3.5 plus browser scripting'],
        ['Humane AI Pin', 'MONO:was $699 + $24/mo',
         '**Dead.** HP acquired Humane\'s software/patents/team for ~$116M in Feb 2025 and shut the '
         'cloud backend off Feb 28, 2025 -- every sold unit stopped working as an AI device that day'],
        ['Friend necklace', 'MONO:$249 (v2, Jul 2026)',
         'Pivoted to companionship/emotional-support framing rather than a tool-calling assistant -- a '
         'different product category'],
    ], [1.3 * inch, 1.6 * inch, 3.45 * inch]),
    ('callout', 'The Humane Pin is the cautionary tale Truffle\'s marketing is built around',
     'Every Humane Pin buyer paid for hardware whose intelligence lived entirely on a vendor\'s servers; '
     'when that vendor\'s business ended, the hardware became e-waste overnight, with zero local '
     'fallback. That\'s the exact failure mode Truffle\'s "exo-cortex, no cloud dependency" pitch is '
     'positioned against -- whatever else is uncertain about a small, low-profile company, an on-device '
     'model can\'t be switched off remotely by an acquirer the way Humane\'s could.'),

    ('h2', '10.3 &middot; Skipping hardware entirely'),
    ('p', 'The lowest-effort alternative is simply not buying a device: use existing phones/laptops with '
          'ChatGPT, Claude, or Gemini. In 2026 all three ship real scheduled/background-agent features -- '
          'OpenAI\'s Scheduled Tasks, Anthropic\'s Claude Cowork, and Google\'s Gemini Spark -- that '
          'partially answer Truffle\'s "proactivity" pitch, though each depends on a companion app staying '
          'reachable rather than running on owned hardware.'),
    ('table', ['Tier', 'Monthly cost', 'Break-even vs. Truffle\'s $1,299'], [
        ['Entry subscription (ChatGPT Plus / Claude Pro / Gemini Pro)', 'MONO:$20/mo', '~65 months (5.4 years)'],
        ['Power tier (ChatGPT Pro / Claude Max / Gemini Ultra)', 'MONO:$100-$200/mo', '6.5-13 months'],
        ['Heavy agentic API usage', 'MONO:$100-$500+/mo, uncapped', 'as little as 1-4 months, then compounds forever'],
    ], [3.15 * inch, 1.5 * inch, 1.7 * inch]),
    ('p', 'The privacy trade is the mirror image of the cost trade: cloud assistants generally out-reason '
          'a mid-size on-device open model, but prompts and connected-app data are processed on vendor '
          'servers, and consumer tiers default to training on conversations unless a user actively opts '
          'out. Worth noting in fairness: Truffle\'s own MCP "apps" (Slack, Gmail, Notion) still send data '
          'to those same third-party clouds whenever actually invoked -- full local sovereignty applies '
          'to the model inference step, not to every connected service.'),

    ('h2', '10.4 &middot; The verdict'),
    ('p', 'For someone who already owns capable Linux/Docker skills and is building a hobby project, a '
          'used-GPU PC (~$1,000-1,700) is the one path that can genuinely undercut Truffle on price while '
          'matching or beating it on raw tokens/sec -- at the cost of weeks of integration work and zero '
          'vendor support if it breaks. For someone who wants the newest, fastest hardware and doesn\'t '
          'mind paying for it, a Mac Studio or a Ryzen AI Max mini-PC gets more headroom for 2-4x the '
          'money. For someone who wants to skip hardware and infrastructure decisions altogether, a cloud '
          'subscription is cheaper for the first year and smarter per query, then gets more expensive '
          'than Truffle for as long as it keeps being used. Truffle\'s actual pitch isn\'t "the cheapest '
          'way to run an LLM at home" -- on 2026 pricing, several DIY paths no longer are -- it\'s the '
          'only option in this list that bundles owned, offline inference with a maintained app '
          'ecosystem, a mobile client, and a standing proactive agent as one product, with one vendor '
          'accountable for all of it staying in sync.'),
]

# ---- 11. The Mac Mini Path -----------------------------------------------------------
s = sec(11, 'macmini', 'The Mac Mini Path -- Building It as an Aspiring AI Engineer',
        'Section 10.1 asked "is a Mac cheaper than a Truffle?" This asks a different question: if the '
        'actual goal is learning to build systems like Truffle rather than owning one, is a Mac mini a '
        'good training platform? The honest answer is yes -- better, in some ways, than either buying a '
        'Truffle or buying the priciest Mac configuration available.')
s['blocks'] += [
    ('h2', '11.1 &middot; Two budgets, two ambitions'),
    ('p', 'The mistake most beginners make is buying the $2,899 64GB configuration on day one because '
          'that\'s the number that showed up in the cost comparison above. It\'s the wrong first purchase '
          'for someone learning, not because it\'s a bad machine, but because the skills below are '
          'learned identically at 8B-model scale as they are at 70B-model scale -- and 8B fits comfortably '
          'on far cheaper hardware.'),
    ('table', ['Tier', 'Hardware', 'Cost', 'What it unlocks'], [
        ['Entry / learning', 'Any Mac with 16-24GB unified memory (base M-series mini, or a Mac already owned)',
         'MONO:$0 (if owned) - ~$799',
         '7-8B quantized models, comfortably fast -- everything in 11.3\'s milestones 1-4 runs fine here'],
        ['Serious / production-scale', 'Mac mini M5 Pro, 64GB/512GB (same config priced in 10.1)',
         'MONO:$2,899',
         '30-70B-class models, the scale where Truffle\'s own on-device model (Qwen 3.6) actually competes'],
    ], [1.35 * inch, 2.3 * inch, 0.95 * inch, 1.75 * inch]),
    ('p', 'Buy the entry tier first. Upgrade only once you\'ve hit a concrete wall the small model can\'t '
          'clear -- that wall, and understanding exactly why it appeared, is itself the lesson.'),

    ('h2', '11.2 &middot; The toolchain, in the order to install it'),
    ('ol', [
        '**Homebrew + Python via `uv`** -- the same environment pattern Truffle\'s own SDK docs recommend '
        '(`docs.truffle.net/sdk/installation` walks through the identical `uv`/`venv` setup).',
        '**`brew install ollama`** -- running `ollama serve` instantly exposes an OpenAI-compatible '
        'endpoint at `localhost:11434/v1`, the same request/response shape as Truffle\'s own `/if2/v1/'
        'chat/completions` covered in Section 6.2. This is the fastest way to see that "an inference API" '
        'is a learnable, ordinary thing, not something only a hardware company can build.',
        '**LM Studio** -- a GUI alternative with a browsable model/quantization catalog and (since '
        'v0.3.17) a **native MCP client**, so it can call the exact class of tool servers described in '
        'Section 6.4.',
        '**`mlx-lm`** (Apple\'s own array framework) -- once the black-box tools feel familiar, drop down '
        'a level and load a model directly in Python via MLX. This is where "quantization," "KV cache," '
        'and "unified memory" stop being words from Section 6.1\'s model-lineage table and become numbers '
        'you can watch move on your own machine.',
    ]),

    ('h2', '11.3 &middot; A milestone roadmap that mirrors Section 6'),
    ('p', 'Every capability Section 6 documented Truffle shipping has a small, buildable equivalent. '
          'Working through them in order is a genuine AI-engineering curriculum, not a toy exercise:'),
    ('table', ['Milestone', 'Build this', 'Mirrors'], [
        ['1. Inference API',
         'Call `ollama serve` with curl and the OpenAI Python SDK pointed at the local base URL. '
         'Practice streaming, temperature/top_p, and structured JSON output.',
         'Sec. 6.2 -- Truffle\'s `/if2/v1/*` endpoints'],
        ['2. Tool calling via MCP',
         'Write a ~30-line MCP server exposing one or two real tools (a file search, a weather lookup). '
         'Connect it to LM Studio or Claude Desktop and watch the model decide when to call it.',
         'Sec. 6.4 -- `ForegroundApp` / `ToolSpec`'],
        ['3. Memory / RAG',
         'Add a local embeddings model (`nomic-embed-text` via Ollama, or an MLX embedding model) plus a '
         'pure-Python vector store (Chroma or LanceDB, no server to run). Point it at a folder of your own '
         'notes.',
         'Sec. 6.3 -- Convo\'s local-embeddings memory layer'],
        ['4. Proactivity',
         'Write a `launchd` or cron job that polls something on a schedule (new GitHub PRs, new email) '
         'and appends a note to a context file the model reads at chat time.',
         'Sec. 6.3 -- `BackgroundWorkerApp.submit_text()`'],
        ['5. Capstone',
         'Wire milestones 1-4 into one small loop that routes between 2-3 tools using the model\'s own '
         'judgment -- a crude, honest rebuild of the "mixture-of-models" classifier from Section 6.1.',
         'Sec. 6.1 -- app-routing / classification'],
    ], [1.05 * inch, 3.9 * inch, 1.4 * inch]),
    ('callout', 'What this teaches that buying the appliance doesn\'t',
     'Debugging a model that calls the wrong tool, or invents an argument that doesn\'t exist, is the '
     'single most common real day-to-day task in AI engineering -- and it\'s invisible if the only agent '
     'you\'ve ever used is a polished consumer product that hides its own failures. The Mac mini\'s own '
     'unified-memory ceiling is a hands-on lesson in exactly the bandwidth-vs-model-size tradeoff '
     'Truffle\'s Jetson hardware faces (Sec. 4, 6.1). And MCP, the protocol you\'d be hand-building a '
     'server for in Milestone 2, is the same standard Truffle\'s current SDK generation converged on '
     '(Sec. 6.4) -- a transferable, increasingly industry-wide skill, not a Truffle-specific party trick.'),

    ('h2', '11.4 &middot; Realistic cost and time'),
    ('p', 'Hardware: $0 if a capable Mac is already owned, or roughly $600-800 for a new base-tier Mac '
          'mini -- a small fraction of either a Truffle ($1,299) or the 64GB configuration priced in '
          '10.1 ($2,899). Time: Milestones 1-2 are a comfortable weekend; 3-4 are one to two weeks of '
          'evenings; 5 is ongoing iteration, the same way any real project keeps evolving. None of it '
          'requires buying a Truffle, a Jetson, or a cloud subscription -- the entire skillset Section 6 '
          'spent this dossier describing is learnable on hardware most people can already reach for.'),
]

# ---- 12. Sources ------------------------------------------------------------------
SOURCES = [
    ('truffle.net', 'marketing site, positioning/vision copy'),
    ('docs.truffle.net', 'SDK installation, CLI, Convo, Convo automation, Inference API, Building Apps, '
                          'Foreground/Background app guides, Install Steps, Release Notes, Client Overview'),
    ('github.com/deepshard', 'organisation overview and repository list'),
    ('github.com/deepshard/trufflesdk', 'original 2024 SDK README ("toolbox in a sandbox," gRPC/Protobuf design)'),
    ('github.com/deepshard/truffle-app-template', 'worked SDK example, publishing flow'),
    ('github.com/deepshard/get-started-with-hyphae', 'Hyphae SDK generation, predicate-gated tools, ArXiv example app'),
    ('github.com/deepshard/AgentRegistry', 'decentralized agent-registry protocol (Solidity, OP-TEE hardware attestation)'),
    ('docs.itsalltruffles.com', 'earlier-generation docs snapshot ("What is a Truffle App?", model list incl. DeepSeek R1 / Gemma3-27B / Qwen)'),
    ('itsalltruffles.com', 'Deepshard corporate landing page'),
    ('Hacker News thread on Truffle-1 (Mar 2024, id 39682422)', 'launch reception and criticism'),
    ('@rohanpaul_ai on X', 'launch benchmark summary'),
    ('@levelsio on X', 'positive take on launch honesty'),
    ('FundersClub -- Deepshard (dba Truffle)', 'company/funding profile'),
    ('YC -- Truffle AI; SecurityWeek -- Truffle Security funding', 'unrelated companies, see naming disambiguation (Sec. 2)'),
    ('NVIDIA Jetson AGX Orin Developer Kit marketplace listing', 'live-verified $3,499 price (Sept 2026)'),
    ('CNX Software -- NVIDIA Jetson price increase (Jul 2026)', ''),
    ('Apple Newsroom -- Mac Studio M5 Max/Ultra (Aug 2026)', ''),
    ('TechCrunch -- Humane AI Pin shutdown, HP acquisition (Feb 2025)', ''),
    ('Wikipedia -- Rabbit R1', 'status and reception'),
    ('Claude pricing (claude.com/pricing); Google AI subscriptions (blog.google)', '2026 power-tier subscription pricing'),
    ('Home Assistant -- AI architecture blog post (Sep 2025)', 'reactive, not autonomous'),
    ('TechRadar -- Beelink GTR9 Pro (Ryzen AI Max+ 395) pricing', ''),
    ('LM Studio MCP docs; Ollama; Apple MLX (github.com/ml-explore/mlx)', 'the Mac-mini toolchain referenced in Sec. 11'),
]

FOOTNOTE = ('Compiled from public web sources between September 9 and September 16, 2026. Truffle is a '
            'fast-moving, weekly-shipping product -- treat specifics (pricing, exact model versions, '
            'feature availability) as a snapshot, and re-check `docs.truffle.net/release-notes` for '
            'anything decision-critical.')

# ============================================================= DOC BUILD =====

class DossierDoc(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, **kw)
        frame = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN - 0.15 * inch,
                       id='normal')
        template = PageTemplate(id='normal', frames=[frame], onPage=self._draw_furniture)
        self.addPageTemplates([template])
        self._bookmark_seq = 0

    def build(self, flowables, **kw):
        self._bookmark_seq = 0
        return super().build(flowables, **kw)

    def _draw_furniture(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - 0.55 * inch, PAGE_W - MARGIN, PAGE_H - 0.55 * inch)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(FAINT)
        canvas.drawString(MARGIN, PAGE_H - 0.42 * inch, 'TRUFFLE RESEARCH DOSSIER')
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.42 * inch, 'truffle.net · Deepshard, Inc.')
        canvas.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
        canvas.drawString(MARGIN, 0.38 * inch, 'Compiled September 2026')
        canvas.drawRightString(PAGE_W - MARGIN, 0.38 * inch, f'Page {doc.page}')
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if not isinstance(flowable, Paragraph):
            return
        style_name = flowable.style.name
        text = flowable.getPlainText()
        if style_name == 'H1':
            self._bookmark_seq += 1
            key = f'bm-{self._bookmark_seq}'
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0, closed=False)
            self.notify('TOCEntry', (0, text, self.page, key))
        elif style_name == 'H2':
            self._bookmark_seq += 1
            key = f'bm-{self._bookmark_seq}'
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=1, closed=True)
            self.notify('TOCEntry', (1, text, self.page, key))


def build_story():
    story = []

    # ---- Title page ----
    story.append(Spacer(1, 0.9 * inch))
    story.append(Paragraph('&#9679;&nbsp;RESEARCH DOSSIER &middot; COMPILED SEPTEMBER 2026', styles['Eyebrow']))
    story.append(Paragraph('Truffle', styles['Title']))
    story.append(Paragraph('The Private Exo-Cortex', ParagraphStyle('T2', parent=styles['Title'],
                                                                      fontSize=19, textColor=ACCENT,
                                                                      spaceAfter=16)))
    story.append(Paragraph(
        'A full walkthrough of truffle.net: the company behind it, the Jetson-based hardware it sells, '
        'the app/agent SDK built on top, how its on-device AI stack is actually engineered, and a '
        'practical build-vs-buy analysis -- including a hands-on path for an aspiring AI engineer '
        'starting from a Mac mini.', styles['Subtitle']))
    story.append(Spacer(1, 10))
    story.append(render_pills(['truffle.net', 'Deepshard, Inc.', 'Los Angeles',
                                'Local-first LLM', 'MCP agent SDK', 'Build vs. buy']))
    story.append(Spacer(1, 26))
    story.append(HRFlowable(width='100%', thickness=0.6, color=BORDER, spaceAfter=14))
    story.append(Paragraph('Contents', ParagraphStyle('ContentsHead', fontName='Helvetica-Bold',
                                                        fontSize=11, textColor=INK, spaceAfter=8)))
    toc = TableOfContents()
    toc.levelStyles = [styles['TOCH1'], styles['TOCH2']]
    story.append(toc)
    story.append(PageBreak())

    # ---- Sections ----
    for i, s in enumerate(SECTIONS):
        story.append(Paragraph(f'{s["num"]} &middot; {s["title"]}', styles['H1']))
        if s['intro']:
            story.append(Paragraph(md(s['intro']), styles['H1sub']))
        story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=10))
        for block in s['blocks']:
            kind = block[0]
            if kind == 'p':
                story.append(P(block[1]))
            elif kind == 'p_dim':
                story.append(P(block[1], 'BodyDim'))
            elif kind == 'h2':
                story.append(Paragraph(block[1], styles['H2']))
            elif kind == 'h3':
                story.append(Paragraph(md(block[1]), styles['H3']))
            elif kind == 'ul':
                story += render_bullets(block[1])
                story.append(Spacer(1, 4))
            elif kind == 'ol':
                story += render_bullets(block[1], ordered=block[2] if len(block) > 2 else True)
                story.append(Spacer(1, 4))
            elif kind == 'table':
                story.append(render_table(block[1], block[2], block[3]))
                story.append(Spacer(1, 10))
            elif kind == 'callout':
                story.append(render_callout(block[1], block[2], warn=False))
            elif kind == 'callout_warn':
                story.append(render_callout(block[1], block[2], warn=True))
            elif kind == 'code':
                story.append(render_code(block[1], block[2]))
            elif kind == 'timeline':
                story += render_timeline(block[1])
                story.append(Spacer(1, 6))
            elif kind == 'namegrid':
                story += render_namegrid(block[1])
            elif kind == 'facts':
                story.append(render_facts(block[1]))
                story.append(Spacer(1, 10))
        story.append(PageBreak())

    # ---- Sources ----
    story.append(Paragraph('12 &middot; Sources', styles['H1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=10))
    for title, desc in SOURCES:
        if desc:
            story.append(Paragraph(f'<b>{esc_amp(title)}</b> &mdash; {md(desc)}', styles['Source']))
        else:
            story.append(Paragraph(f'<b>{esc_amp(title)}</b>', styles['Source']))
    story.append(Paragraph(md(FOOTNOTE), styles['Footnote']))

    return story


if __name__ == '__main__':
    doc = DossierDoc('Truffle_Research_Dossier.pdf', pagesize=(PAGE_W, PAGE_H),
                      title='Truffle Research Dossier', author='Research compilation')
    doc.multiBuild(build_story())
    print('PDF built.')
