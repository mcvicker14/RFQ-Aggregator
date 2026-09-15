# Core User Flows

## 1. New opportunity enters the pipeline

```
BD staffer finds a lead (SAM.gov sync OR manual entry)
        │
        ▼
Opportunity created — stage = "Signal Detected", is_sample_data = false,
provenance recorded (source, source_url, retrieved_at)
        │
        ▼
Principal Pursuit Score auto-calculated on create and on every relevant field edit
        │
        ▼
Appears on Dashboard "Highest Priority Opportunities" if score/deadline warrant it
        │
        ▼
Staffer moves stage to "Researching" → "Capture" as work happens (Pipeline view)
        │
        ▼
Go/No-Go review created, criteria scored, AI recommendation shown,
a human (Administrator/Executive/BD) records the actual GO / CONDITIONAL GO / NO-GO
        │
        ├─ NO-GO  → stage set to "No Bid", opportunity archived from active pipeline
        └─ GO     → stage advances through Teaming → Solicitation Released →
                     Proposal Development → Submitted → Shortlisted → Interview →
                     Negotiation → Award Pending → Won/Lost
```

## 2. Solicitation document analysis

```
User opens an opportunity → Documents tab → uploads RFP/RFQ/SF330 instructions (PDF/DOCX)
        │
        ▼
File stored (local disk in dev; StorageBackend interface for S3/Azure later),
opportunity_documents row created
        │
        ▼
User clicks "Analyze with AI"
        │
        ▼
Backend extracts text → sends to Claude with a strict JSON extraction prompt
        │
        ├─ ANTHROPIC_API_KEY not set → 503, UI shows "AI analysis not configured"
        │                              with plain-English setup instructions
        └─ configured → structured result stored (ai_solicitation_analyses),
                         rendered as Executive Summary, Top 10 Things to Know,
                         Potential Red Flags — every field traceable to the source
                         document, nothing silently added to the opportunity record
                         without the user reviewing it
```

## 3. Go/No-Go decision

```
Open opportunity → Go/No-Go tab → "Start Review" (if none exists) or view existing
        │
        ▼
Score each configured criterion 1–5 (strategic alignment, client relationship,
past performance, technical capability, key personnel, geographic advantage,
teaming strength, competitive position, profitability, proposal effort, schedule,
contract risk, probability of award, SDVOSB advantage, incumbent strength)
        │
        ▼
System computes an AI Recommendation (weighted average → suggested GO/CONDITIONAL/NO-GO)
— shown as "AI Recommendation Factors", never as a final decision
        │
        ▼
A human with permission (Administrator/Executive/BD) records the actual decision
— decided_by and decided_at stored, immutable history of prior reviews kept
```

## 4. Daily use ("What should I work on today?")

```
User logs in → Dashboard
        │
        ├─ KPI cards: pipeline value, weighted pipeline, due in 30 days, awaiting Go/No-Go, etc.
        ├─ "Highest Priority Opportunities" (top 10 by score × urgency)
        ├─ "What Needs Attention Today" (open tasks due today/overdue, across all opportunities)
        └─ Alerts panel (deadlines approaching, new SAM.gov matches since last sync, amendments)
```

## 5. Revenue forecasting

```
Opportunity detail → Forecast tab → enter total contract value, Principal's estimated
share, estimated fee, win probability, expected award date
        │
        ▼
Weighted value = estimated fee × probability, computed server-side and stored
        │
        ▼
/forecast page aggregates by month / quarter / year / agency / market / stage,
shows Total Pipeline, Weighted Pipeline, and (once won opportunities exist)
Committed Revenue vs. an admin-settable Target Revenue → Revenue Gap
```
