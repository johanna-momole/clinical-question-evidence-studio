# Evidence Ranking

## Overview

After metatagging, `rank_records()` in `src/evidence/ranking.py` assigns each `EvidenceRecord` a `relevance_score ∈ [0.0, 1.0]`. The score is a weighted sum of five components derived from the record's tags and date.

---

## Scoring Formula

```
relevance_score = (
    population_score  * 0.30 +
    intervention_score * 0.30 +
    outcome_score     * 0.20 +
    design_score      * 0.10 +
    recency_score     * 0.10
)
```

All component scores are in [0.0, 1.0].

---

## Component Definitions

### Population Score (weight 0.30)

Binary: 1.0 if any `population:*` tag is present on the record, 0.0 otherwise.

A `population:*` tag is assigned by the metatagging rule when the record's text contains keywords from the query's population PICO term list (e.g. "type 2 diabetes", "t2dm", "hba1c").

### Intervention Score (weight 0.30)

Binary: 1.0 if any `intervention:*` tag is present, 0.0 otherwise.

### Outcome Score (weight 0.20)

Binary: 1.0 if any `outcome:*` tag is present, 0.0 otherwise.

### Design Score (weight 0.10)

Graded by study design hierarchy:

| Tag | Score |
|---|---|
| `design:meta_analysis` or `design:systematic_review` | 1.0 |
| `design:rct` | 0.8 |
| `design:observational` | 0.5 |
| `design:review` | 0.3 |
| Any other `design:*` tag | 0.2 |
| No `design:*` tag | 0.0 |

### Recency Score (weight 0.10)

Linear decay based on `publication_or_update_date`:

```
years_old = (today - pub_date).days / 365.25

if years_old <= 2:   recency_score = 1.0
elif years_old >= 10: recency_score = 0.0
else:
    recency_score = 1.0 - (years_old - 2) / 8.0
```

Records with `publication_or_update_date = None` receive `recency_score = 0.0`.

---

## Score Interpretation

| Score range | Interpretation |
|---|---|
| 0.80 – 1.00 | Highly relevant — matches population, intervention, outcome, strong design, recent |
| 0.50 – 0.79 | Moderately relevant — matches 2–3 PICO dimensions |
| 0.20 – 0.49 | Partially relevant — matches 1 PICO dimension or has strong design without PICO match |
| 0.00 – 0.19 | Low relevance — no PICO tag matches |

Scores are for **sorting and filtering only**. They are not clinical recommendations and do not assess evidence quality, methodological rigor, or applicability to any individual patient.

---

## Sort Order

Records returned by the API and displayed in the Streamlit UI are sorted by `relevance_score DESC NULLS LAST`. Records with equal scores preserve their original fixture/retrieval order.

---

## Limitations

- The scoring is entirely tag-driven. Tags are assigned by keyword rules, not by reading the full text of each article.
- A record that discusses the correct population and intervention but uses non-standard terminology may score 0.0 on those dimensions even though it is clinically relevant.
- The design hierarchy is based on the PubMed publication type label or the ClinicalTrials study type. These labels are self-reported by authors/sponsors and may not always accurately characterize the study.
- Recency does not account for study duration, delay to publication, or post-publication update status.
