# Module 01: OSINT Profiler

**Phase:** Reconnaissance  
**MITRE ATT&CK:** T1593.001 · T1589.002 · T1598.003  
**Output:** `output/profiles.json`, `output/pretext_template.txt`, `output/events.jsonl`

---

## What It Does

The OSINT Profiler automates Phase 1 of the Scattered Spider simulation. It scrapes three simulated
public sources (a fake LinkedIn employee directory, a job postings feed, and a multi-page company
website), extracts and correlates identity data across all sources, scores each employee as a
potential social-engineering target, and produces a ranked list of attack profiles along with a
ready-to-use vishing pretext script for the highest-value target.

The output feeds directly into Module 03 (vishing scripts) and Module 04 (MFA fatigue simulator)
via the shared profile schema.

---

## Running It

```bash
cd modules/01-osint-profiler

# Run the full pipeline
python profiler.py

# Run tests
pytest tests/test_profiler.py -v
```

Output files are written to `output/`:

| File | Contents |
|---|---|
| `profiles.json` | All 20 target profiles, sorted by attack value |
| `sample_profile.json` | Top-ranked target only (for quick inspection) |
| `pretext_template.txt` | Filled vishing script for the highest-value target |
| `events.jsonl` | MITRE-tagged event log (one JSON object per line) |

---

## Architecture

```
01-osint-profiler/
├── profiler.py          # Main pipeline: orchestrates all steps, writes output
├── connectors/          # Data source layer (simulated, no real network calls)
│   ├── __init__.py      # LinkedInConnector, JobPostingConnector, WebsiteConnector
│   ├── employees.json   # 20 simulated employees (LinkedIn source data)
│   ├── job_postings.json
│   └── website/         # 7-page SimCorp website (scraped for phones/emails/SSO)
│       ├── index.html
│       ├── about.html
│       ├── leadership.html
│       ├── services.html
│       ├── contact.html
│       ├── careers.html
│       └── it-support.html
├── extractors/
│   └── __init__.py      # Identity, email, phone, and SSO extractors
├── tests/
│   └── test_profiler.py # 60 unit tests across all issues
└── output/              # Generated at runtime (gitignored)
```

---

## Pipeline: Step by Step

### Step 1: Harvest Simulated Sources (Issue #36)

Three connectors each scrape a whitelisted source and wrap results in a provenance envelope:

```python
{
  "scrape_id": "<uuid>",
  "source_id": "linkedin" | "job_postings" | "company_website",
  "scraped_at": "<ISO-8601 UTC>",
  "data": { ... }
}
```

**`LinkedInConnector`** reads `employees.json`, 20 simulated employees with name, title,
department, and manager. Each employee gets one raw record.

**`JobPostingConnector`** reads `job_postings.json`, several mock job postings. The bodies
explicitly mention `Okta` as a required skill, which is what SSO detection picks up.

**`WebsiteConnector`** iterates over all 7 HTML pages in `connectors/website/` and returns
one raw record per page. Each record contains the list of phone numbers, email addresses,
and Okta mentions extracted by regex from that page's HTML. The profiler has to navigate
all pages to assemble a complete picture, phones are on `contact.html`, executive emails
on `leadership.html`, Okta portal details on `it-support.html`, etc.

**Safety:** `_assert_whitelisted(source_id)` is called before every scrape. Any source ID
not in `{"linkedin", "job_postings", "company_website"}` raises `SourceNotWhitelisted`,
making it impossible for a connector to call out to a real external host.

---

### Step 2: Detect SSO Provider (Issue #40)

`detect_sso_provider(records)` in `extractors/__init__.py` scans job postings and website
records for exact keyword matches against:

```
Okta, SSO, Single Sign-On, Okta administrator, SAML, identity provider
```

Uses `re.escape()` on each keyword, no fuzzy matching. Returns on the first match with:

```json
{
  "provider": "Okta",
  "evidence_snippet": "...surrounding 60 chars...",
  "confidence": "explicit",
  "source_id": "job_postings",
  "scrape_id": "<uuid>"
}
```

In the SimCorp dataset, Okta is mentioned in multiple job postings and across three website
pages (`about.html`, `careers.html`, `it-support.html`), so detection always succeeds.

---

### Step 3: Extract Phone Numbers (Issue #39)

`extract_phone_numbers(website_record)` processes each website page record. For each phone
number regex match, it re-reads the raw HTML to grab an 80-character context window around
the number and checks whether `helpdesk`, `IT support`, or `service desk` appears nearby.
Numbers with that context are labelled `"helpdesk"`; others are `"general"`.

Phone normalisation via `_normalise_phone()`:

| Input | Output |
|---|---|
| `6135550100` | `+1-613-555-0100` |
| `(613) 555-0100` | `+1-613-555-0100` |
| `613.555.0100` | `+1-613-555-0100` |
| `+1-613-555-0100` | `+1-613-555-0100` (pass-through) |

Returns a list of dicts per page:
```json
{
  "raw": "+1-613-555-0100",
  "normalised": "+1-613-555-0100",
  "label": "helpdesk",
  "confidence": "explicit",
  "snippet": "...surrounding HTML context...",
  "source_id": "company_website",
  "scrape_id": "<uuid>"
}
```

---

### Step 4: Build Identity Profiles (Issues #37, #38)

For each LinkedIn employee record, two extractors run:

**`extract_identity(record)`**: parses name (splits on whitespace for first/last), title,
department, manager, and normalises the title to a role group:

| Title keywords | Role group |
|---|---|
| helpdesk, it support, support specialist | `Helpdesk` |
| it administrator, systems administrator, okta administrator, network engineer, devops, it director, security analyst | `IT_Admin` |
| chief executive/financial/technology, ceo/cfo/cto, vp of, vice president, director | `Executive` |
| finance analyst/manager, legal, hr, sales | `Staff` |

**`infer_email_candidates(first, last, explicit_emails, domain)`**: produces up to 3 candidate
email addresses per person using frequency analysis on emails found in the website pages:

1. If the website explicitly contains an email matching this person's first or last name,
   it is ranked #1 with confidence `"explicit"`.
2. The most common email pattern across all explicit website emails is detected
   (`first.last`, `f.last`, or `firstlast`) and used as the #1 inferred candidate.
3. Remaining patterns fill slots 2 and 3 with confidence `"inferred"`.

For the SimCorp dataset, `leadership.html` exposes `claire.fontaine@simcorp.com`,
`james.okafor@simcorp.com`, etc., so those get confidence `"explicit"`. Remaining
staff get confidence `"inferred"` pattern-matched candidates.

---

### Step 5: Score and Rank Targets (Issues #37, #41)

Each profile is assigned an **attack value** (1–10) based on role group:

| Role group | Attack value | Rationale |
|---|---|---|
| `Helpdesk` | 9 | Can reset passwords and remove MFA on request |
| `IT_Admin` | 8 | Has direct system access and provisioning rights |
| `Executive` | 7 | High credibility for impersonation pretexts |
| `Staff` | 4 | Lower access; useful for lateral context only |

Profiles above the `FLAG_THRESHOLD` of 8 trigger `FLAG_1_RECON_COMPLETE` in the event log.
In the SimCorp dataset this is always triggered, the Helpdesk team (Tyler Brennan, Mariam
Diallo, Kevin Ashworth, David Osei) all score 9.

---

### Step 6: Generate Vishing Pretext Template (Issue #41)

For the top-ranked target, `_generate_pretext_template()` fills a fixed script template:

```
VISHING PRETEXT: SIMULATED EXERCISE USE ONLY
==============================================
Scenario: Senior employee locked out while travelling

CALLER SCRIPT:
"Hi, this is {name}, {title} here at SimCorp. I'm currently travelling in
London, UK and I'm completely locked out of my account..."
```

Fields populated from the profile:
- Name, title, department, manager (from LinkedIn)
- Top email candidate and Okta username (`firstlast` format)
- SSO provider (from job postings detection)
- Helpdesk phone number (from website pages)
- Confidence notes on any inferred fields
- Evidence summary showing which source each field came from

Written to `output/pretext_template.txt`.

---

### Step 7: Export JSON Profiles (Issue #42)

All profiles are written to `output/profiles.json`, sorted descending by `attack_value`.
The schema per profile:

```json
{
  "id": "<uuid>",
  "employee_id": "emp_005",
  "name": "Tyler Brennan",
  "first": "Tyler",
  "last": "Brennan",
  "title": "IT Support Specialist",
  "role_group": "Helpdesk",
  "department": "Helpdesk",
  "manager": "Rebecca Nwosu",
  "email_candidates": [
    { "address": "tyler.brennan@simcorp.com", "pattern": "first.last", "confidence": "inferred", "rank": 1 },
    { "address": "t.brennan@simcorp.com",     "pattern": "f.last",     "confidence": "inferred", "rank": 2 },
    { "address": "tylerbrennan@simcorp.com",   "pattern": "firstlast",  "confidence": "inferred", "rank": 3 }
  ],
  "phone_numbers": [
    { "raw": "+1-613-555-0100", "normalised": "+1-613-555-0100", "label": "helpdesk", "confidence": "explicit" }
  ],
  "okta_username": "tylerbrennan",
  "sso_provider": "Okta",
  "attack_value": 9,
  "source_id": "linkedin",
  "provenance_log": [
    { "step": "identity_extraction", "source_id": "linkedin", "scrape_id": "<uuid>", "timestamp": "...", "confidence": "explicit" }
  ],
  "created_at": "<ISO-8601 UTC>"
}
```

---

### Step 8: Emit MITRE-Tagged Event Log (Issue #43)

Every significant pipeline action writes a structured event to `output/events.jsonl`
(one JSON object per line, append mode):

```json
{
  "event_id": "<uuid>",
  "timestamp": "<ISO-8601 UTC>",
  "phase": 1,
  "technique_id": "T1593.001",
  "tactic": "reconnaissance",
  "description": "Scraped simulated LinkedIn directory: 20 records",
  "source_module": "01-osint-profiler",
  "flag_triggered": "FLAG_1_RECON_COMPLETE",
  "raw_data": { ... }
}
```

| Event | Technique |
|---|---|
| LinkedIn scrape complete | T1593.001: Search Open Websites/Domains |
| Job postings scrape complete | T1598.003: Phishing for Information |
| SSO provider detected | T1598.003 |
| Profiles built and ranked | T1589.002: Gather Victim Identity Info |

`FLAG_1_RECON_COMPLETE` is set on the final event when the top target's `attack_value >= 8`.

---

## Safety Controls

| Control | Implementation |
|---|---|
| Whitelist enforcement | `_assert_whitelisted()` called before every connector scrape; raises `SourceNotWhitelisted` on any non-whitelisted ID |
| No network calls | All connectors read local files only; no `requests`, `httpx`, or socket calls anywhere in the module |
| Simulated data only | All 20 employees, job postings, and website pages are synthetic, no real person's data |
| Exercise labelling | Every page in the website carries `SIMULATED ENVIRONMENT, FOR EXERCISE USE ONLY` in the footer; the pretext template header reads `SIMULATED EXERCISE USE ONLY` |

---

## Test Coverage

```
pytest tests/test_profiler.py -v   # 60 tests, ~0.2s
```

| Test class | What it covers |
|---|---|
| `TestWhitelistEnforcement` (8) | Whitelist passes and raises; connector SOURCE_IDs stay whitelisted |
| `TestConnectorOutput` (10) | Provenance envelope fields; connector return types and record counts |
| `TestIdentityExtraction` (9) | Name splitting, role group normalisation, confidence, snippet format |
| `TestEmailInference` (10) | Candidate count, schema, domain, pattern ranking, deduplication, empty input |
| `TestPhoneExtraction` (6) | Field presence, helpdesk labelling, normalisation, source_id |
| `TestSSODetection` (6) | Okta detection, evidence snippet, false-positive guard, None on no match |
| `TestExportStructuredJSON` (5) | `profiles.json` written, valid JSON, required fields, sort order |
| `TestProvenanceAndSafeguards` (5) | Event log written, valid JSON, FLAG_1 triggered, whitelist blocks external |

---

## Data Flow Diagram

```
employees.json ──► LinkedInConnector ──►
                                         │
job_postings.json ► JobPostingConnector ─┼─► profiler.run()
                                         │        │
website/*.html ──► WebsiteConnector ─────┘        │
                   (7 pages, 1 record each)        │
                                                   ▼
                                         extract_identity()        ← LinkedIn records
                                         infer_email_candidates()  ← website emails
                                         extract_phone_numbers()   ← website records
                                         detect_sso_provider()     ← job postings + website
                                                   │
                                                   ▼
                                         Score & rank profiles (attack_value)
                                                   │
                                         ┌─────────┴──────────┐
                                         ▼                     ▼
                                  profiles.json        pretext_template.txt
                                  sample_profile.json  events.jsonl
```
