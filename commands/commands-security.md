# Commands — `security` branch, direct copy-paste

Stage 2 of 3. Everything from `commands-basic-rag.md` **plus** the
reliability layer: the Model Armor safety guardrail, the LiteLLM
Gemini→Groq router, the scope guardrail, the semantic cache, LangSmith
evaluation, and the red-team suite. Still **no** OAuth and **no** Cloud Run
— those are `deployment`.

Real values below. Shell: Git Bash. Gitignored — never committed.

---

## Values used on this branch

```bash
PROJECT_ID=rag-hr-assistant-demo
PROJECT_NUMBER=5648199
REGION=us-central1
LOCATION=us-central1
MODEL_ARMOR_LOCATION=us
MODEL_ARMOR_TEMPLATE_ID=hr-assistant-guardrail
```

Extra secrets this branch can use (both optional — only `evaluate.py` and
the Groq fallback need them): `GROQ_API_KEY` (console.groq.com),
`LANGSMITH_API_KEY` (smith.langchain.com). Put them in `.env`.

---

## 1. Enable the Model Armor API

`basic-rag` already enabled `aiplatform` + `storage`. Security adds one:

```bash
gcloud services enable modelarmor.googleapis.com --project=$PROJECT_ID

# Confirm
gcloud services list --enabled --project=$PROJECT_ID \
  --filter="config.name:modelarmor.googleapis.com" --format="value(config.name)"
```

## 2. Create the Model Armor guardrail template (one-time)

This template screens every input and every output for prompt injection,
jailbreaks, and unsafe content.

```bash
gcloud model-armor templates create $MODEL_ARMOR_TEMPLATE_ID \
  --location=$MODEL_ARMOR_LOCATION \
  --project=$PROJECT_ID \
  --pi-and-jailbreak-filter-settings-enforcement=enabled \
  --pi-and-jailbreak-filter-settings-confidence-level=high \
  --basic-config-filter-enforcement=enabled \
  --rai-settings-filters=confidenceLevel=high,filterType=HATE_SPEECH \
  --rai-settings-filters=confidenceLevel=high,filterType=HARASSMENT \
  --rai-settings-filters=confidenceLevel=high,filterType=DANGEROUS \
  --rai-settings-filters=confidenceLevel=high,filterType=SEXUALLY_EXPLICIT \
  --malicious-uri-filter-settings-enforcement=enabled

# Confirm it exists
gcloud model-armor templates describe $MODEL_ARMOR_TEMPLATE_ID \
  --location=$MODEL_ARMOR_LOCATION --project=$PROJECT_ID
```

**No Model Armor template? Run locally without it:** set
`GUARDRAIL_PROVIDER=gemini_lite` in `.env` (one cheap Gemini classify call,
no GCP setup) or `GUARDRAIL_PROVIDER=none` (guardrail off).

## 3. Install the LiteLLM packages

`security`'s `llm.py` routes Vertex Gemini → Groq through a LiteLLM Router.
Two packages `basic-rag` didn't need:

```bash
source hrrenv/Scripts/activate
uv pip install -r requirements.txt      # adds litellm + langchain-litellm (+ others)
```

## 4. `.env` additions for this branch

Already covered by `.env.example`. Beyond `basic-rag`'s vars:

```bash
GUARDRAIL_PROVIDER=model_armor
MODEL_ARMOR_LOCATION=us
MODEL_ARMOR_TEMPLATE_ID=hr-assistant-guardrail
QDRANT_NOISY_COLLECTION_NAME=hr_policies_noisy_demo
# optional — only for evaluate.py and the Groq fallback:
GROQ_API_KEY=...
LANGSMITH_API_KEY=...
LANGSMITH_TRACING=true
```

Guardrail tuning knobs (`GUARDRAIL_FAIL_OPEN_INPUT`/`_OUTPUT`,
`GUARDRAIL_HISTORY_TURNS`, `SEMANTIC_CACHE_MAX_ENTRIES`/`_TTL_SECONDS`) all
have sensible defaults — leave unset unless tuning.

## 5. Ingest (same corpus, same bucket as `basic-rag`)

```bash
python ingest.py        # only if you haven't already — both collections are reused as-is
```

## 6. Run it

```bash
python main.py                  # CLI — full secure pipeline (guardrails + scope filter + cache)
streamlit run app.py            # chat UI — sidebar shows the active guardrail provider
python demo_reliability.py      # guarded-pipeline walkthrough against the noisy corpus
langgraph dev                   # LangGraph Studio — the guarded agent
python -m hr_assistant.tracing  # confirm LangSmith tracing
```

## 7. Adversarial red-team pass

```bash
python redteam_test.py     # 7 attacks vs the plain baseline AND the guarded pipeline
                           # -> results/redteam_results.json + results/RED_TEAM_TEST_RESULTS.md
```

Expect the input guardrail to BLOCK `instruction_override` and
`dan_jailbreak` before retrieval, and the guarded pipeline to hold 7/7.

## 8. Answer-quality evaluation

Needs `LANGSMITH_API_KEY` + `GROQ_API_KEY` in `.env`.

```bash
python evaluate.py    # correctness + groundedness, judged by Groq gpt-oss-120b
                      # -> a LangSmith experiment on the dataset named in
                      #    hr_assistant/evaluation_dataset.py (DATASET_NAME)
```

The eval runs the **guarded** agent (guarded search tool + reliability
prompt + cache) against the **noisy** collection — the same stack the app
uses, under the harder cross-domain-noise conditions.

## 9. Recreate the Model Armor template (reference only — already exists)

If you ever need to delete + rebuild it, use the exact command in step 2.
To delete:
```bash
gcloud model-armor templates delete $MODEL_ARMOR_TEMPLATE_ID \
  --location=$MODEL_ARMOR_LOCATION --project=$PROJECT_ID
```

## Cost note

Same as `basic-rag`, plus: Model Armor screens 2 calls per request (input +
output) at Gemini-Flash-adjacent pricing; Groq's free tier covers the
fallback + eval judge at this volume; LangSmith's free tier covers tracing
+ the eval dataset easily.

## If something breaks

See `docs/17-troubleshooting.md`. Common on this branch: input guardrail
failing **closed** because the Model Armor template/API isn't set up
(switch to `GUARDRAIL_PROVIDER=gemini_lite`), or `langgraph dev` conflicting
with a baked-in checkpointer (fixed on this branch — `studio_graph.py`
builds with `checkpointer=False`).
