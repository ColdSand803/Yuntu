# Yuntu Architecture & Design Principles

## Core Philosophy: Deterministic Core + Creative Periphery

Most AI travel planning tools suffer from serious hallucinations:
- Recommending fake restaurants or permanently closed spots.
- Planning absurd routes (e.g. crossing a whole city 4 times in a single day).
- Hallucinating prices, travel durations, and transport schedules.

**Yuntu is built with strict separation between deterministic logic and LLM creativity:**

```text
User Request (Natural Language or Structured Form)
  │
  ▼
[ 1. Intent Parser (LLM) ]
  Extracts destination, days, budget, preferences, pacing, avoid list.
  │
  ▼
[ 2. Data Retrieval (Pure SQL + Geo-filtering) ]
  NO LLM. Strict SQL query against verified canonical POIs and accommodation areas.
  │
  ▼
[ 3. Route Planning & Grouping (Deterministic Math & Geo Routing) ]
  NO LLM. Daily commute budget optimization, intra-district spatial clustering,
  Haversine distance minimization, and arrival/departure logistics.
  │
  ▼
[ 4. Final Writer (LLM with Strict Structured Evidence Payload) ]
  Generates fluent travel narrative and rich day-by-day advice.
  LLM is prohibited from inventing facts not present in the verified POI payload.
  │
  ▼
[ 5. Quality & Publish Gate (Deterministic Rules + Review) ]
  Automated checks for route containment, hotel fabrication, price claims,
  and transit consistency. Hard-stop veto power.
  │
  ▼
Structured Plan Output (JSON / Markdown / Export Artifacts)
```

---

## Key Modules

### 1. `src/agents/intent_parser.py`
Parses free-form Chinese/multilingual queries into structured `TripRequest` schemas.

### 2. `src/agents/data_retrieval.py`
Queries `travel_canonical_place` for verified, active POIs with real latitude/longitude coordinates and category tags.

### 3. `src/agents/route_planning.py`
Determines which POIs go to which day, their visit order, and daily commute efficiency using spatial geometry and AMap transit/driving routing.

### 4. `src/agents/accommodation_resolver.py`
Calculates the optimal accommodation neighborhood (商圈) that minimizes total travel distance to all visited POIs.

### 5. `src/agents/final_writer.py` & `src/agents/publish_gate.py`
Produces engaging markdown travel guides while strictly policing against hallucinated attractions or fake prices.
