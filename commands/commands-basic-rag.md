# Commands — `basic-rag` branch, direct copy-paste

Stage 1 of 3. The plain RAG pipeline only: retrieval → hybrid search →
re-rank → agent → cited answer. **No** Model Armor, **no** OAuth, **no**
Cloud Run, **no** LiteLLM router, **no** eval/red-team — those come in
`security` and `deployment`.

Real values below. Shell: Git Bash (matches `hrrenv/Scripts/activate`).
Gitignored — never committed.

---

## Values used on this branch

```bash
PROJECT_ID=rag-hr-assistant-demo
PROJECT_NUMBER=56481199
REGION=us-central1
LOCATION=us-central1
GCS_BUCKET_NAME=rag-hr-assistant-demo-hr-policies
BILLING_ACCOUNT_ID=01F83E-4931F0-126013
QDRANT_COLLECTION_NAME=hr_policies
QDRANT_NOISY_COLLECTION_NAME=hr_policies_noisy_demo
```

`JINA_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY` are real secrets — get your
own from **jina.ai** and **cloud.qdrant.io** (both free tier), put them in
`.env`. They never get typed into any command.

---

## 1. GCP project + billing (skip if the project already exists)

```bash
gcloud auth login

# See your billing account ID
gcloud billing accounts list

# Create the project
gcloud projects create $PROJECT_ID --name="RAG HR Assistant Demo"

# Link billing — nothing chargeable works without this
gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ACCOUNT_ID

# Make it the default for every command below
gcloud config set project $PROJECT_ID
```

## 2. Point local credentials at the project

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project $PROJECT_ID
```

## 3. Enable the two APIs this branch needs

```bash
gcloud services enable aiplatform.googleapis.com storage.googleapis.com --project=$PROJECT_ID

# Confirm
gcloud services list --enabled --project=$PROJECT_ID \
  --filter="config.name:(aiplatform.googleapis.com OR storage.googleapis.com)" \
  --format="value(config.name)"
```

- `aiplatform.googleapis.com` — Vertex AI, the Gemini model.
- `storage.googleapis.com` — Cloud Storage, holds the raw HR documents.

## 4. Create the Cloud Storage bucket

```bash
gcloud storage buckets create gs://$GCS_BUCKET_NAME \
  --project=$PROJECT_ID \
  --location=$REGION

# Confirm
gcloud storage buckets describe gs://$GCS_BUCKET_NAME --format="value(name,location)"
```

`ingest.py` uploads `data/` into this bucket — you don't upload manually.

## 5. Python environment

```bash
uv venv hrrenv
source hrrenv/Scripts/activate       # Git Bash / macOS / Linux
uv pip install -r requirements.txt
```

## 6. `.env`

```bash
cp .env.example .env
```

Fill in: `PROJECT_ID`, `LOCATION`, `GCS_BUCKET_NAME`, `JINA_API_KEY`,
`QDRANT_URL`, `QDRANT_API_KEY`. `config.py` reads `.env` automatically via
`python-dotenv` — no other wiring.

## 7. Ingest the corpus into Qdrant

```bash
# local data/ -> GCS raw/ -> GCS processed/ -> chunk -> embed -> Qdrant
# Builds BOTH collections (hr_policies + hr_policies_noisy_demo).
# Idempotent — skips a collection that already has data.
python ingest.py

# Rebuild from scratch, or limit scope:
python ingest.py --force
python ingest.py --hr-only        # skip the noisy/mixed collection
python ingest.py --noisy-only     # skip the clean collection
```

## 8. Run it

```bash
python main.py                    # CLI demo — a few questions through the agent
streamlit run app.py              # chat UI at http://localhost:8501
langgraph dev                     # LangGraph Studio — inspect the agent graph
python -m hr_assistant.tracing    # confirm LangSmith tracing (if LANGSMITH_TRACING=true)
```

## Cost note

Vertex AI Gemini Flash and Jina are pay-per-call at near-zero volume for
local dev. Qdrant Cloud and Jina free tiers cover this easily. Nothing on
this branch runs standing infrastructure.

## If something breaks

See `docs/17-troubleshooting.md`. Most common on this branch: a Qdrant
collection missing (`Run python ingest.py`) or the Jina key not set.
