# RankEngine — SEO Execution Register & Cadence Reports

**Spec for Antigravity · v1.0 draft**
Reference: `Maintenance_Execution_Register.html` (SOW-02, Fluid Controls). Security / operations / governance content in that reference is **out of scope** — SEO tasks only.

---

## 0. Goal

RankEngine generates, per site:

1. An **SEO Execution Register** dashboard — every recurring SEO task, grouped by cadence (weekly / monthly / quarterly), with capability, last run, next due and honest state.
2. **Three cadence reports** exported from the same data: Weekly Pulse, Monthly SEO Report, Quarterly Strategy Review (HTML + PDF).

The reference's strength is that it *judges state honestly* ("can we produce the deliverable this period, from what exists, without building something first") and surfaces gaps ordered by exposure. Preserve that: the register must never show a task as done without evidence.

### Hard constraints (existing, unchanged)

- Single-tenant, no auth, no billing. Sites are not tenants; scope data by `siteId`.
- Stack: Node/Express/TypeScript API (:3000), React/Vite frontend (:8080), Python/Playwright/BullMQ worker (:8000), MongoDB, Redis. Shared types live in the monorepo shared package.
- **Verified-data rule:** own-site rankings come only from GSC Search Analytics; competitor positions come only from Playwright SERP snapshots. A mandatory post-generation validation pass rejects any report containing an unverified ranking claim.
- Follow existing API route and error conventions; paths below are indicative.

---

## 1. What carries over from the reference, and what doesn't

| Reference element | Decision |
|---|---|
| Masthead stamp (doc id, version, date, confidentiality) | Keep. Doc id format `RE/{siteSlug}/{cadence}/{periodKey}` |
| Scope frame (KPI strip of boundaries) | Keep, repurposed: connectors, tracked keywords, last crawl, next report due |
| Readiness tally (11 exist / 7 partial / 6 to build) | Keep as **two** tallies: capability (auto / assisted / manual) and this-period state (done / due / overdue / blocked) |
| Pillar tables: Service · Quoted commitment · How we execute · Cadence · State | Keep, as Cadence sections grouped by pillar. Columns in §5 |
| Inline "honest part / missing / decide once" notes | Keep — generated from real findings (baseline ratchet, missing connector, blocked source) |
| Operating rhythm (Week 1–4 + unattended clock + quarterly) | Keep, generated from the schedule |
| Gap register ordered by exposure | Keep, computed (§5.6) |
| Boundary section (what is not covered) | Keep, shorter: explicit exclusions and data-provenance commitments |
| Source / verification footer | Keep — each run lists what data it was verified against and when |
| Pillar 4 — security scanning, patching, uptime, backups, incident SLA, vendor accountability | **Drop** |
| Hours ledger, change requests, licence line, fee boundaries | **Drop** (commercial) |
| Board report | Keep as Monthly SEO Report; strategy review kept as Quarterly |

Pillars used: **Technical SEO & Site Health · On-Page & Content · Off-Page & Authority · Reporting & Strategy**.

---

## 2. Task catalog (seed data)

**Mode** = what the platform can do for the task:
- **Auto** — platform runs it and produces the result without a human.
- **Assisted** — platform drafts / queues / diagnoses; a human approves or acts.
- **Manual** — a human does it; platform tracks due date, collects evidence, shows state.

**Done when** is the evidence rule. A task is `done` only when a `TaskRun` exists in the period window with the listed evidence attached.

### 2.1 Weekly — monitoring; catch regressions early (window: Mon–Sun)

| ID | Task | Pillar | Mode | Source | Done when |
|---|---|---|---|---|---|
| W1 | Search performance pulse: clicks, impressions, CTR, position week-over-week; top gainers/losers (queries and pages) | On-page | Auto | GSC | Snapshot stored; movers beyond threshold flagged. Note GSC lag (last ~3 days partial) |
| W2 | Indexation watch: sitemap status, submitted vs indexed, URL Inspection sample of priority + newly published URLs | Technical | Auto | GSC (Sitemaps, URL Inspection) | Sample inspected; non-indexed priority URLs listed |
| W3 | Crawl-health delta on priority URLs: new 4xx/5xx, redirect chains, noindex / canonical / robots / sitemap changes | Technical | Auto | Playwright worker crawl | Diff vs previous run stored; regressions flagged |
| W4 | Core Web Vitals regression check on key templates | Technical | Auto | Lighthouse (lab); CrUX/PSI (field, if available) | Compared with baseline; regressions flagged |
| W5 | Priority-keyword SERP snapshot (competitor positions, SERP features) | Off-page | Auto | Playwright SERP snapshots | Snapshot stored — builds the history monthly analysis needs |
| W6 | New/changed page QA: every page published or edited this week passes title, description, H1, canonical, schema, alt-text checks | On-page | Auto | Crawl of changed URLs | Checked-URL list stored; failures queued |
| W7 | Editorial pipeline check: was this week's article slot published? | On-page | Manual | Editorial calendar | Slot marked published / slipped with reason |
| W8 | Brand mention & review alert digest — logged even when empty | Off-page | Manual | Alerts / manual entry | Digest line logged ("no mentions, no reviews" is a valid entry) |

### 2.2 Monthly — the core execution cycle (window: calendar month)

| ID | Task | Pillar | Mode | Source | Done when |
|---|---|---|---|---|---|
| M1 | Full-site technical crawl and audit, findings logged by severity, compared to baseline (ratchet, §6.4) | Technical | Auto | Playwright crawl | Audit stored; findings vs baseline computed |
| M2 | Crawl-error resolution: 4xx, redirect chains, orphan pages, index errors — fixed, not just reported | Technical | Assisted | Crawl + GSC | Queue items fixed or accepted-with-reason; each fix has a diff / redirect-map / content change reference |
| M3 | Core Web Vitals monthly review; regressions diagnosed and repaired | Technical | Assisted | Lighthouse + CrUX/PSI | Trend stored; each regression has a diagnosis and an owner |
| M4 | Structured data validation: template-level schema grading + Rich Results spot-check | Technical | Assisted | Crawl (JSON-LD grading) + manual Rich Results test | Zero new schema errors, or logged; spot-check URLs recorded (the audit proves we emit it; only Google proves it is accepted) |
| M5 | Sitemap & robots hygiene: reconcile sitemap vs crawl vs indexed | Technical | Auto | Crawl + GSC | Reconciliation diff stored |
| M6 | Image SEO pass: alt-text coverage, descriptive filenames, weight, next-gen formats | Technical | Assisted | Crawl | Coverage % stored vs previous month |
| M7 | AEO / GEO visibility panel: a fixed set (~20) of buyer questions put to each tracked AI assistant; presence and citation recorded | Technical | Assisted | AI/GEO visibility track (manual entry until automated) | Panel results stored so the report carries a trend, not an assertion |
| M8 | Keyword & ranking review: priority terms, underperformers, striking distance (positions 8–20), cannibalisation | On-page | Auto | GSC | Review list stored; underperformers routed into M9 |
| M9 | Meta-tag optimisation cycle: draft → verify → review queue → apply | On-page | Assisted | GSC (CTR) + crawl | Approved changes applied; before/after tracked. Nothing applied unreviewed |
| M10 | Content freshness sweep: stale pages ranked by age and traffic decay | On-page | Assisted | Crawl + GSC + `reviewedOn` | `reviewedOn` updated on swept pages |
| M11 | Search-growth content: publish the planned articles; book next month's slots | On-page | Manual | Editorial calendar | Published count vs planned; next month's slots booked |
| M12 | Optimise new/updated pages received this month (catalogue, product, landing) | On-page | Assisted | Site connector / manual | Before/after comparison attached (reuse existing before/after report) |
| M13 | Citation & directory register: verify a slice, correct drift against the NAP source of truth | Off-page | Manual | Citation register | Slice verified; corrections logged |
| M14 | Backlink review: new/lost links; reclamation list (broken inbound links, unlinked mentions) | Off-page | Assisted | Manual GSC UI export + Firecrawl verification (see §9) | Profile snapshot stored; reclamation list updated |
| M15 | Outreach batch (white-hat only), every send and reply logged | Off-page | Manual | Outreach register | Batch logged |
| M16 | Competitor tracking: rankings, keywords, authority proxy, content velocity | Off-page | Auto | SERP snapshots (W5 history) + crawl | Competitor data stored; included in the Monthly SEO Report |
| M17 | Brand & reputation watch: monthly line in the report | Off-page | Manual | Alerts / manual entry | Line logged, including "nothing found" months |
| M18 | Monthly SEO Report assembled, validated, issued; next month's plan agreed | Reporting | Auto-assembled | All of the above | Immutable `ReportSnapshot` issued; plan section populated |

### 2.3 Quarterly — strategy and deep audits (window: calendar quarter; scheduled in its last 4 weeks so full-quarter data is available)

| ID | Task | Pillar | Mode | Source | Done when |
|---|---|---|---|---|---|
| Q1 | Quarterly strategy review: performance vs goals; next-quarter roadmap | Reporting | Assisted | 3 trailing monthly reports + open queues | Quarterly report issued; roadmap has an acceptance record |
| Q2 | Keyword research refresh and keyword-map rebuild | On-page | Assisted | Google Ads Keyword Planner + GSC + Playwright Autocomplete/PAA | New keyword map stored; changes vs previous map listed |
| Q3 | Content inventory audit: keep / improve / merge / redirect / remove decision per page group | On-page | Assisted | Crawl + GSC + GA4 | Decisions recorded and queued |
| Q4 | Site architecture & internal-linking review: click depth, hubs, topical clusters | Technical | Assisted | Crawl | Findings and link-change queue stored |
| Q5 | Competitive gap analysis: keyword, content, SERP-feature and authority gaps | Off-page | Assisted | SERP snapshot history + crawl | Gap list stored, ranked by opportunity |
| Q6 | Backlink deep audit and link-gap vs competitors; clean-up decisions | Off-page | Manual | Manual export / Firecrawl | Audit stored; actions logged |
| Q7 | Algorithm & guideline impact review: core updates and Google guideline changes vs traffic movement | Reporting | Manual | GSC + GA4 + annotations | Review note stored; follow-up tasks created |
| Q8 | AEO / GEO strategy review: refresh the prompt panel, quarter trend | Technical | Assisted | M7 history | Updated panel and trend stored |
| Q9 | Measurement integrity audit: GA4 key events, GSC–GA4 link, property settings, filters | Reporting | Manual | GA4 + GSC | Checklist completed with results |
| Q10 | Deep technical audit: JS-rendered vs raw crawl comparison, mobile usability, hreflang (if multilingual), log-file analysis (if logs available) | Technical | Assisted | Worker | Audit stored; inapplicable parts marked "n/a with reason" |
| Q11 | Local SEO / Business Profile audit (toggle off unless the site has local intent) | Off-page | Manual | Manual | Audit stored, or task disabled with reason |

Totals: 8 weekly, 18 monthly, 11 quarterly. Event-driven work (migration, redesign, a core update) is not scheduled; it creates ad-hoc tasks.

**Per-site toggles:** each task can be disabled for a site, but only with a recorded reason (e.g. Q11 "no local intent"). Disabled tasks appear in the register as `n/a` and are excluded from tallies.

---

## 3. Data model (shared types)

```ts
type Cadence = 'weekly' | 'monthly' | 'quarterly';
type Pillar = 'technical' | 'onpage' | 'offpage' | 'reporting';
type Mode = 'auto' | 'assisted' | 'manual';
type SourceId = 'gsc' | 'ga4' | 'crawl' | 'serp_snapshot' | 'lighthouse'
              | 'crux' | 'firecrawl' | 'keyword_planner' | 'manual';

interface SeoTaskDef {            // seeded from §2, versioned
  id: string;                     // 'W1' | 'M9' | 'Q3' ...
  cadence: Cadence;
  pillar: Pillar;
  title: string;
  commitment: string;             // one-sentence deliverable
  howItRuns: string;              // plain-language execution note
  mode: Mode;
  sources: SourceId[];
  doneWhen: string;
  scheduleHint: { week?: 1|2|3|4; cron?: string };  // auto jobs carry a cron
  dependsOn?: string[];           // e.g. M18 depends on M1, M8, M16
}

interface SiteTaskConfig { siteId: string; taskId: string; enabled: boolean; disabledReason?: string; }

type RunStatus = 'done' | 'skipped' | 'failed';
interface TaskRun {
  id: string; siteId: string; taskId: string; periodKey: string; // '2026-W41' | '2026-10' | '2026-Q4'
  status: RunStatus; startedAt: string; finishedAt: string;
  triggeredBy: 'schedule' | 'manual';
  skipReason?: string;
  evidence: EvidenceRef[];        // required when status === 'done'
  metrics: Metric[];
  notes?: string;                 // free text from a human
}

interface EvidenceRef { kind: 'audit' | 'snapshot' | 'diff' | 'report' | 'register_entry' | 'url'; ref: string; }

interface Metric {
  key: string; value: number | string; unit?: string;
  source: SourceId;
  fetchedAt: string; periodStart: string; periodEnd: string;
  verified: boolean;              // false for manual entry until confirmed
}

interface Finding {               // output of crawl audits and queues
  id: string; siteId: string; taskId: string; severity: 'blocking'|'high'|'medium'|'low';
  check: string; url?: string; firstSeen: string; lastSeen: string;
  status: 'open'|'fixed'|'accepted'; acceptedReason?: string; fixRef?: string;
}

interface ReportSnapshot {        // immutable once issued
  id: string; siteId: string; cadence: Cadence; periodKey: string;
  docId: string;                  // RE/{siteSlug}/{cadence}/{periodKey}
  issuedAt: string; dataThrough: string;  // honest end date given source lag
  sections: ReportSection[]; metricsUsed: string[];  // Metric ids
  validation: { passed: boolean; checkedAt: string; rejected: string[] };
}
```

**Derived period state** per task and period (computed, not stored):

| State | Rule | Chip colour (reference tokens) |
|---|---|---|
| `done` | `TaskRun.status = done` in window with evidence | `ok` |
| `due` | Window open, no run yet, no blocker | `part` |
| `overdue` | Window closed (or past `scheduleHint` by grace period) with no run | `gap` |
| `blocked` | Required source not connected or required input missing | `gap` |
| `skipped` | Run with `status = skipped` and a reason | `part` |
| `n/a` | Disabled for the site | neutral |

**Capability** (static per task): `auto` → `ok`, `assisted` → `part`, `manual` → `gap` chip colour in the capability tally only.

---

## 4. Scheduling

- BullMQ repeatable jobs, cron per task, evaluated in a **per-site timezone** setting (default UTC).
- Default times: Weekly jobs Monday 06:00; monthly full crawl and audit on the 1st–3rd (week 1); monthly report generation on a configurable day in week 4; quarterly tasks start 4 weeks before quarter end.
- Auto tasks write `TaskRun`s themselves. Assisted/manual tasks create an open item whose completion form requires evidence.
- A nightly sweep recomputes derived state and marks `overdue`. Do not store derived state as the source of truth.

### Default operating rhythm (rendered in §5.5)

| Week | Placement |
|---|---|
| Week 1 | M1 full crawl and audit · M5 sitemap/robots · M3 CWV review · M11 book article slots |
| Week 2 | M2 crawl-error queues · M8 keyword review · M9 meta cycle · M6 image pass · M13 citation slice |
| Week 3 | M10 freshness sweep · M4 schema spot-check · M7 AEO panel · M14 backlink review · M15 outreach batch · M12 on-receipt pages |
| Week 4 | M16 competitor run · M17 brand line · M18 report assembled, validated, issued, next plan agreed |
| Unattended | Weekly W1–W6 on Mondays; W7/W8 reminders |
| Quarterly | Q1–Q11 spread across the last 4 weeks of the quarter; Q1 last |

---

## 5. Dashboard spec

Route: `/sites/:siteId/register`. One shared React component tree rendered two ways: live in the app, and via server-side render (`renderToStaticMarkup`) to **standalone HTML** for export. This keeps the dashboard and exported report from drifting.

### 5.1 Masthead
- Stamp row (mono, uppercase): `RE/{siteSlug}/{periodKey}` · period · generated at · data-through date.
- H1: "SEO Execution Register".
- Standfirst — **templated from counts, not LLM-written**: "{N} recurring SEO tasks across four pillars. {a} done this period, {b} due, {c} overdue, {d} blocked. Data verified against GSC (fetched {t}) and crawl ({t})."

### 5.2 Scope frame (KPI strip, 1px-gap grid)
Cells: Site · Connectors (GSC / GA4 state) · Tracked keywords · Pages in last crawl · Last full crawl · Competitors tracked · Next report due.

### 5.3 Readiness tally
Two rows of three large numbers:
1. **Capability:** Auto · Assisted · Manual.
2. **This period:** Done · Due · Overdue/Blocked.
Short sentence under each, as in the reference ("A command or workflow already produces the deliverable").

### 5.4 Cadence sections (Weekly, Monthly, Quarterly)
Each: eyebrow ("Cadence · Monthly"), H2, one-line description, then one table per pillar.

Columns: **Task** (left border coloured by state) · **Commitment** · **How it runs** · **Last run** · **Next due** · **State** (chip).

Under rows where something is worth saying, render a `note` callout generated from data, for example:
- *The honest part:* "{n} blocking findings stand today. A check getting worse fails the ratchet; raising the baseline is a logged acceptance." (M1)
- *Missing:* "GSC has no links API; backlink movement is only as fresh as the last manual export ({date})." (M14)
- *Missing:* "No `reviewedOn` date on {n} pages, so ageing cannot be ranked." (M10)
- *Decide:* "AEO panel has {k} entries, all manual — presence trend is unverified." (M7)

Rows expand to show the last run's evidence links, metrics and open findings.

### 5.5 Operating rhythm
Four week cards (§4 table) plus "On a clock, unattended" (each auto job's next fire time) and a Quarterly list. Tasks link into their register rows.

### 5.6 Gap register — "What to close before the report is trustworthy"
Computed list, ordered by exposure (highest first):
1. **Blocked** tasks whose source is not connected (e.g. GA4 missing blocks Monthly report traffic section).
2. **Overdue** tasks that feed a report (dependency graph via `dependsOn`), weighted by how far past the window.
3. **Overdue** tasks with no downstream report.
4. **Manual-only** tasks with no register entries in the last 2 periods (the "watch nobody is running" case).
5. **Unverified data**: tasks whose metrics are all `verified: false`.

Each gap shows: title, one-paragraph reason, **Underwrites:** the report section(s) or task(s) that depend on it.

### 5.7 Boundary & provenance footer
- **Not covered:** security scanning, patching, uptime, backups, incident response, non-English editions unless configured.
- **Provenance commitments:** own rankings from GSC only; competitor positions from SERP snapshots only; manual entries are labelled `manual`; "no data" is stated, never silently omitted.
- Source line: doc id, data-through date, crawl run id, GSC fetch timestamp.

### 5.8 API (indicative)

| Method | Path | Purpose |
|---|---|---|
| GET | `/sites/:siteId/register?periodKey=` | Full register state: tasks, derived states, tallies, gaps |
| GET | `/sites/:siteId/tasks/:taskId/runs` | Run history with evidence |
| POST | `/sites/:siteId/tasks/:taskId/runs` | Record a manual/assisted completion (evidence required for `done`) |
| PATCH | `/sites/:siteId/tasks/:taskId/config` | Enable/disable (reason required) |
| POST | `/sites/:siteId/reports` | Body `{cadence, periodKey}` — generate, validate, issue |
| GET | `/sites/:siteId/reports` | List issued snapshots |
| GET | `/sites/:siteId/reports/:id` · `/html` · `/pdf` | JSON, standalone HTML, PDF (worker Playwright print) |

---

## 6. Reports

All reports are immutable `ReportSnapshot`s with a `dataThrough` date. Periods ending today include only data through `min(periodEnd, today − source lag)`, stated in the stamp.

### 6.1 Weekly Pulse (1 page)
1. Headline numbers: clicks, impressions, CTR, avg position vs prior week (W1)
2. Movers: top 5 gainers / losers, queries and pages (W1)
3. Technical changes: new errors, indexation issues, CWV flags (W2–W4)
4. SERP snapshot highlights: priority keywords where a competitor moved (W5)
5. New-page QA failures (W6)
6. This week's tasks: done / due / overdue, publishing status (W7, W8)

### 6.2 Monthly SEO Report (readable by a director in five minutes)
1. Summary — templated sentences from computed deltas; optional Claude narrative only if it passes validation (§7)
2. Traffic — GA4 organic sessions and key events, MoM and YoY
3. Search performance — GSC clicks, impressions, CTR, position; movers
4. Rankings — priority terms (GSC); striking-distance and cannibalisation lists (M8)
5. Technical health — findings vs baseline, CWV trend, indexation, schema, images (M1–M6)
6. AI-answer visibility — panel results and trend (M7)
7. Content — articles published vs planned, pages refreshed, meta changes applied with before/after (M9–M12)
8. Off-page — links gained/lost with data source and date, citations verified, outreach log, brand line (M13–M15, M17)
9. Competitors — rankings, keyword overlap, content velocity (M16). **Included every month without exception.**
10. Work completed — the register for the month: done / skipped / overdue, each with evidence
11. Next month's plan — drawn from open queues and the booked editorial slots

Each section states "no data" with the reason when it has none.

### 6.3 Quarterly Strategy Review
1. Performance vs goals — three trailing monthly reports rolled up
2. Keyword map changes (Q2)
3. Content audit decisions (Q3)
4. Architecture & internal linking (Q4)
5. Competitive gap analysis (Q5) and link gap (Q6)
6. Algorithm & guideline impact (Q7)
7. AI visibility strategy (Q8)
8. Measurement integrity (Q9) and deep technical audit (Q10); local audit (Q11) if enabled
9. Proposed roadmap — candidate items from open queues, ranked by impact and effort; **accepted-by and accepted-on fields** make it a dated, agreed roadmap

### 6.4 Baseline ratchet (carried from the reference)
- First full crawl sets the **baseline** per check (counts by severity).
- Later crawls compare per check. A check getting worse is a **regression**, flagged in the register and the report.
- Raising a baseline requires an explicit acceptance (reason, date) stored on the baseline record — never automatic.
- Show the current blocking-finding count honestly, even when large.

### 6.5 Reuse
Existing per-page performance reports and before/after comparison reports remain; the register links to them as evidence on M9, M12 and Q3.

---

## 7. Generation pipeline and validation

1. **Collect** — pull metrics for the period, each with `source`, `fetchedAt`, `periodStart`, `periodEnd`, `verified`.
2. **Assemble** — templated sections computed in the API from stored metrics. No free-form numbers.
3. **Narrate (optional)** — if Claude writes any prose, it must reference metrics by id; it receives only stored metrics.
4. **Validate (mandatory, existing rule extended)** — reject the snapshot if:
   - any numeric claim lacks a `Metric` reference;
   - any own-site ranking claim does not trace to `gsc`;
   - any competitor position does not trace to `serp_snapshot`;
   - any `verified: false` metric is presented as fact without a "manual" label;
   - any section is empty without an explicit "no data, because …" line.
5. **Issue** — freeze the snapshot; render HTML; PDF on request.
6. On rejection, store the failed draft with `validation.rejected` for review; never issue it.

Data caveats the generator must state, not hide:
- GSC data lags; the last few days of the period are partial.
- GSC exposes no links API; backlink figures are as fresh as the last manual export or Firecrawl verification.
- URL Inspection is a quota-limited sample, not full coverage.
- AEO/GEO panel results entered by hand are labelled `manual`.

---

## 8. Visual design tokens (from the reference)

Fonts: **Archivo** (display), **Source Sans 3** (body), **IBM Plex Mono** (labels). Self-hosted or Google Fonts with real fallback stacks. Tables scroll inside their own container; layout max-width ~1140px; light/dark via `prefers-color-scheme` with a `[data-theme]` override.

```css
:root {
  --ground:#f4f5f7; --surface:#ffffff; --surface-2:#eceef1;
  --ink:#15191e; --ink-2:#3c4653; --steel:#5c6775;
  --rule:#d5d9df; --rule-soft:#e4e7eb;
  --brass:#9c6b16; --brass-soft:#f0e6d2;
  --ok:#1c6655; --ok-soft:#dcebe6;
  --part:#8a5a09; --part-soft:#f6ead3;
  --gap:#9e3123; --gap-soft:#f7e0dc;
}
:root[data-theme="dark"] {
  --ground:#111419; --surface:#191d23; --surface-2:#21262e;
  --ink:#eef1f4; --ink-2:#c3cbd4; --steel:#8e99a6;
  --rule:#2e353e; --rule-soft:#262c34;
  --brass:#d6a24a; --brass-soft:#30281a;
  --ok:#5bbda4; --ok-soft:#16302a;
  --part:#d7a14a; --part-soft:#302616;
  --gap:#e2786a; --gap-soft:#351d19;
}
```

Patterns to reproduce: mono uppercase eyebrow in brass above each H2; stamp row with a 2px ink rule beneath; 1px-gap grid for the scope frame; tables with a mono uppercase header row on `--surface-2`; first-column left border coloured by state (`ok` / `part` / `gap`); rounded-none chips for state; note callouts with a brass left rule.

If the in-app theme should differ, swap token values only; the information architecture stays.

---

## 9. Open decisions (need an owner's call before build)

1. **Backlink data source (M14, Q6):** GSC has no links API. Choose: monthly manual export from the GSC UI, or Firecrawl-verified checks (narrow trial per the earlier evaluation), or both. Decide before the first Monthly report.
2. **AEO/GEO panel (M7, Q8):** which assistants and how results are captured. Until automated, entries are manual and labelled so.
3. **Brand & review watch (W8, M17):** no capability exists yet. Start as a manual log with an explicit "nothing found" entry.
4. **LLM narrative in reports:** allowed only through §7 validation, or templated sentences only for v1?
5. **Editorial calendar:** needed by W7, M11 — does the platform own it (new collection) or import from elsewhere?

---

## 10. Build order and acceptance

| Phase | Scope | Acceptance |
|---|---|---|
| 1 | Task catalog seed, `TaskRun` / `Metric` / `Finding` models, derived-state computation, register API and read-only dashboard (§5.1–5.4) | Register renders all 37 tasks with correct state from seeded runs; disabling requires a reason |
| 2 | Weekly auto jobs W1–W6 wired to GSC, crawl, Lighthouse, SERP snapshots; Weekly Pulse | Pulse generated on schedule; every number traceable to a `Metric` |
| 3 | Monthly auto jobs M1, M5, M8, M16; baseline ratchet; manual/assisted completion forms with evidence | Ratchet flags a worsened check; a `done` run without evidence is rejected |
| 4 | Monthly SEO Report assembler, validation pass, HTML + PDF export | Report with a fabricated ranking claim is rejected; empty sections show "no data, because …" |
| 5 | Operating rhythm (§5.5), gap register (§5.6), boundary footer | Missing GA4 appears as the top gap, "underwrites" the traffic section |
| 6 | Quarterly tasks and Quarterly Strategy Review with roadmap acceptance | Review issued from three trailing monthly snapshots; roadmap carries accepted-by and date |
