# LLM Governance

## Principles

1. **LLM does not silently define the phenotype.** All terminology mappings suggested by an LLM are labeled `is_llm_suggested: true` and start as `review_status: "candidate"`. A human must review and approve each mapping before it can be used in a production context.

2. **All LLM-generated text is labeled.** The `claim_type` field on every `GeneratedClaim` distinguishes `llm_summary` from `retrieved_fact`, `cohort_result`, and `human_reviewed` content. The UI renders these with different visual treatments.

3. **Every factual claim must have a source.** The `is_cited` field on `GeneratedClaim` must be `True` for all claims that derive from external evidence. Uncited clinical claims trigger a QA failure.

4. **No causal claims from observational or synthetic data.** The `is_causal` field on `GeneratedClaim` must be `False` for any claim derived from synthetic cohorts or observational literature. Causal language triggers a QA warning.

5. **Prompt and model version are logged.** Every LLM call records the prompt hash and model ID in a `ProvenanceRecord`. This supports reproducibility and audit.

6. **Deterministic demo mode is always available.** The `DemoLLMClient` returns pre-computed responses so the application functions completely without API keys.

## Provider Interface

The `BaseLLMClient` abstract class defines the interface. The factory function `get_llm_client()` selects the appropriate implementation based on `LLM_PROVIDER` and `DEMO_MODE` settings. Switching providers requires only an environment variable change.

## Disclaimer Requirements

The `EvidenceBrief.disclaimer` field is required and pre-populated. It must be displayed to all users of the brief. The Streamlit UI enforces this by rendering the disclaimer at the top of the Evidence Brief page.
