# Commands — `deployment` branch, direct copy-paste

Everything from `commands-basic-rag.md` and `commands-security.md` still
applies (project, bucket, `.env`, ingest, Model Armor, LiteLLM). This file
is **only** what `deployment` adds: Docker, Google OAuth + an employee
allow-list, and Google Cloud Run.

Real values below — confirmed against this project. Shell: Git Bash.
Gitignored — never committed.

---

## Values used on this branch

```bash
PROJECT_ID=rag-hr-assistant-demo
PROJECT_NUMBER=564821241199
REGION=us-central1
GCS_BUCKET_NAME=rag-hr-assistant-demo-hr-policies
COMPUTE_SA=564821241199-compute@developer.gserviceaccount.com
CLOUD_RUN_SERVICE=hr-rag-assistant
SECRET_NAME=streamlit-auth
# The service URL is assigned on the first deploy. For this project it is:
SERVICE_URL=https://hr-rag-assistant-564821241199.us-central1.run.app
```

---

## 1. Enable the APIs Cloud Run needs

`basic-rag` already turned on `aiplatform` + `storage`; `security` added
`modelarmor`. Deployment adds four more. Safe to run even if some are
already on — it's a no-op then.

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project=$PROJECT_ID

# Confirm all seven the project needs are on:
gcloud services list --enabled --project=$PROJECT_ID \
  --filter="config.name:(aiplatform.googleapis.com OR storage.googleapis.com OR modelarmor.googleapis.com OR run.googleapis.com OR cloudbuild.googleapis.com OR artifactregistry.googleapis.com OR secretmanager.googleapis.com)" \
  --format="value(config.name)"
```

## 2. Grant the Cloud Run service account its permissions

The container runs as the **default compute service account**
(`$COMPUTE_SA`). It needs to call Gemini, read the bucket, call Model Armor,
and read the one OAuth secret. Least-privilege — nothing more.

```bash
# Call Gemini (Vertex AI)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$COMPUTE_SA" --role="roles/aiplatform.user"

# READ (not write) the documents in the bucket
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$COMPUTE_SA" --role="roles/storage.objectViewer"

# Call the Model Armor screening API
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$COMPUTE_SA" --role="roles/modelarmor.user"

# Confirm:
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:$COMPUTE_SA" \
  --format="table(bindings.role)"
```

(The Secret Manager accessor role is granted in step 5, scoped to the one
secret rather than project-wide.)

## 3. Fill the two local config files

Both are gitignored — safe to hold real values.

### `deploy.env.yaml` — plain config + API keys (passed as `--env-vars-file`)

```yaml
PROJECT_ID: "rag-hr-assistant-demo"
LOCATION: "us-central1"
GCS_BUCKET_NAME: "rag-hr-assistant-demo-hr-policies"
QDRANT_COLLECTION_NAME: "hr_policies"
QDRANT_NOISY_COLLECTION_NAME: "hr_policies_noisy_demo"
GUARDRAIL_PROVIDER: "model_armor"
MODEL_ARMOR_LOCATION: "us"
MODEL_ARMOR_TEMPLATE_ID: "hr-assistant-guardrail"
LANGSMITH_TRACING: "true"
LANGSMITH_ENDPOINT: "https://api.smith.langchain.com"
LANGSMITH_PROJECT: "hrragwithgcp"
JINA_API_KEY: "<from your .env>"
QDRANT_URL: "<from your .env>"
QDRANT_API_KEY: "<from your .env>"
GROQ_API_KEY: "<from your .env>"
LANGSMITH_API_KEY: "<from your .env>"
ALLOWED_EMPLOYEE_EMAILS: "mentordivesh@gmail.com"
```

Notes:
- YAML format is `KEY: "value"` — colon-space, value quoted, one per line.
  This handles the commas in `ALLOWED_EMPLOYEE_EMAILS` cleanly (a plain
  `--set-env-vars` string would choke on them).
- `REGION` is **not** here — the app doesn't read it; you pass
  `--region=us-central1` on the deploy command instead.
- `LANGSMITH_TRACING` must be the string `"true"` (quoted).

### `.streamlit/secrets.toml` — OAuth only (goes to Secret Manager, step 5)

```toml
[auth]
redirect_uri = "https://hr-rag-assistant-564821241199.us-central1.run.app/oauth2callback"
cookie_secret = "<openssl rand -hex 32>"

[auth.google]
client_id = "<from the Console, step 4>"
client_secret = "<from the Console, step 4>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

**The `redirect_uri` MUST end in `/oauth2callback`** and must match a URI
registered on the OAuth client **character-for-character**. Getting this
wrong is the #1 deploy failure — see `docs/17-troubleshooting.md`.

Generate the cookie secret:
```bash
openssl rand -hex 32
```

## 4. Create the Google OAuth client (Console — no CLI for this)

1. **console.cloud.google.com** → project `rag-hr-assistant-demo` →
   search **"Google Auth Platform"** (older UI: "OAuth consent screen").
2. **Get started** → App name `HR Policy Assistant`, support email
   `mentordivesh@gmail.com`, **Audience: External**, contact email → Create.
3. **Audience** tab → **Test users** → **+ Add users** →
   `mentordivesh@gmail.com` → Save.
   *(While the app is in "Testing", only emails here can log in at all —
   Google's own gate, separate from `ALLOWED_EMPLOYEE_EMAILS`.)*
4. **Clients** tab → **+ Create client** → Application type **Web
   application** → name `hr-rag-streamlit`.
5. Under **Authorized redirect URIs** → **+ Add URI**, add BOTH:
   ```
   http://localhost:8501/oauth2callback
   https://hr-rag-assistant-564821241199.us-central1.run.app/oauth2callback
   ```
   (localhost for local testing, the run.app one for production.)
   → **Create**.
6. The popup shows **Client ID** (`564821241199-….apps.googleusercontent.com`)
   and **Client secret** (`GOCSPX-…`). Copy both into
   `.streamlit/secrets.toml`. The secret is shown once — if you lose it,
   "Add secret" / reset on the client page gives a new one.

## 5. Upload the OAuth secret to Secret Manager

```bash
# Create the secret (first time only)
gcloud secrets create $SECRET_NAME --data-file=.streamlit/secrets.toml --project=$PROJECT_ID

# ...OR add a new version if it already exists (e.g. you changed redirect_uri)
gcloud secrets versions add $SECRET_NAME --data-file=.streamlit/secrets.toml --project=$PROJECT_ID

# Let the Cloud Run service account read this ONE secret (not project-wide)
gcloud secrets add-iam-policy-binding $SECRET_NAME \
  --member="serviceAccount:$COMPUTE_SA" \
  --role="roles/secretmanager.secretAccessor" \
  --project=$PROJECT_ID
```

## 6. Ingest the corpus (once, if not already done)

Cloud Run bootstraps ingestion on the first request if a collection is
missing, but that first request then takes minutes. Do it up front:

```bash
python ingest.py            # local venv
# or:  docker compose run --rm ingest
```

If you already ran `python ingest.py` on `basic-rag` or `security`, the
collections exist — skip this.

## 7. Deploy — build + push + run, one command

`--source .` sends the repo to Cloud Build, which builds the image from the
`Dockerfile` (using `uv`), pushes it to Artifact Registry, and deploys it.
**You never run `docker build` yourself.**

```bash
gcloud run deploy $CLOUD_RUN_SERVICE \
  --source . \
  --project=$PROJECT_ID \
  --region=$REGION \
  --allow-unauthenticated \
  --set-secrets=/app/.streamlit/secrets.toml=$SECRET_NAME:latest \
  --env-vars-file=deploy.env.yaml
```

- `--allow-unauthenticated` is intentional — the network is public, the
  real gate is the OAuth + allow-list check inside `app.py` (see doc 13).
- Takes 3–5 min the first time, ~1 min after that.
- The output ends with `Service URL: https://hr-rag-assistant-564821241199.us-central1.run.app`.

## 8. Close the OAuth loop (only needed if the URL was unknown at step 4)

If you already added the `run.app` redirect URI in step 5, skip this.
Otherwise: Console → **Clients** → your client → **Authorized redirect
URIs** → add `https://<service-url>/oauth2callback` → Save → wait ~5 min →
re-run step 7 is **not** needed (Console-only change), just retry login.

If you had to change `redirect_uri` in `secrets.toml`, then:
```bash
gcloud secrets versions add $SECRET_NAME --data-file=.streamlit/secrets.toml --project=$PROJECT_ID
gcloud run deploy $CLOUD_RUN_SERVICE --source . --project=$PROJECT_ID --region=$REGION \
  --allow-unauthenticated \
  --set-secrets=/app/.streamlit/secrets.toml=$SECRET_NAME:latest \
  --env-vars-file=deploy.env.yaml
```

## 9. Verify

```bash
# The live URL
gcloud run services describe $CLOUD_RUN_SERVICE --region=$REGION --format="value(status.url)"

# Logs — look for: "LangSmith tracing ENABLED", "INPUT GUARDRAIL: pass",
# "CACHE HIT", and no tracebacks
gcloud run services logs read $CLOUD_RUN_SERVICE --region=$REGION --limit=50
```

Open the URL in an **incognito window** → "Log in with Google" →
`mentordivesh@gmail.com` → the chat appears. A non-listed email →
"not on the approved list".

## 10. Change the employee allow-list later

Two places, both required (see doc 13):
1. Console → Audience → Test users → add/remove the email.
2. Re-deploy with the updated list:
   ```bash
   # edit ALLOWED_EMPLOYEE_EMAILS in deploy.env.yaml, then:
   gcloud run deploy $CLOUD_RUN_SERVICE --source . --project=$PROJECT_ID --region=$REGION \
     --allow-unauthenticated \
     --set-secrets=/app/.streamlit/secrets.toml=$SECRET_NAME:latest \
     --env-vars-file=deploy.env.yaml
   ```

## 11. Local run with Docker (optional — for testing before deploy)

```bash
gcloud auth application-default login          # once
export GCLOUD_CONFIG="$APPDATA/gcloud"         # Windows Git Bash only
docker compose up                              # app at http://localhost:8501
docker compose run --rm ingest                 # one-off ingestion
docker compose run --rm eval                   # one-off evaluation
```

Without `.streamlit/secrets.toml` mounted, the app runs in **"open local
mode"** — no login screen. That's expected locally; the OAuth gate only
engages when the secret is present (as it is on Cloud Run).

## 12. Teardown (deployment-specific — see `commands.md` Phase 14 for the rest)

```bash
gcloud run services delete $CLOUD_RUN_SERVICE --region=$REGION --project=$PROJECT_ID
gcloud secrets delete $SECRET_NAME --project=$PROJECT_ID
```
Then delete the OAuth client in the Console (Clients tab).

## Cost note

Cloud Run scales to zero when idle — no standing cost. Cloud Build is free
at these image sizes; Artifact Registry storage for one image is
negligible; Secret Manager's first 6 versions/month are free. Everything
from `commands-security.md` still applies on top.
