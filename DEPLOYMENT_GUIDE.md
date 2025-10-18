# PCC Platform – Production Deployment Guide  
Deploying React + FastAPI SaaS to Google Cloud Run with MongoDB Atlas & Custom Domain

---

## 1. Overview

The Private Client Consultants (PCC) platform is a full-stack application:

| Layer | Stack | Container |
|-------|-------|-----------|
| Frontend | React 18 + Vite | `frontend/Dockerfile` |
| API | FastAPI + Pydantic | `backend/Dockerfile` |
| Worker (AI tasks, queues) | FastAPI / Celery | `worker/Dockerfile` |

All three services are deployed as individual Cloud Run services.  
State is stored in MongoDB Atlas (shared across services).

```
+------------+      HTTPS       +-----------+
|  Browser   | <--------------> |  FE Run   |
+------------+                  +-----------+
                                      │ REST / WebSocket
                                  +-----------+
                                  | API Run   |
                                  +-----------+
                                      │ MongoDB SRV
                              +-----------------------+
                              |  MongoDB Atlas (M0+)  |
                              +-----------------------+
```

---

## 2. Prerequisites

| Tool | Tested Version |
|------|----------------|
| gcloud SDK | ≥ 473.0 |
| docker | ≥ 24 |
| node | ≥ 20 (for local builds) |
| Python | ≥ 3.11 (scripts) |

Accounts / assets you need beforehand:

1. **Google Cloud Project** with billing enabled (`PROJECT_ID`).
2. **MongoDB Atlas** organisation (free M0 works for dev).
3. **Stripe** account (live & test keys).
4. **Custom Domain** you own (DNS provider access).

---

## 3. Repository Layout & Scripts

```
deploy-gcp.sh              # ⬅ master deployment script (uses gcloud)
.env.example               # template env file
docker/                    # multi-stage Dockerfiles
cloudbuild.yaml            # optional CI pipeline
infra/terraform            # optional IaC (not mandatory)
```

`deploy-gcp.sh` can deploy **all** or **individual** services:

```
./deploy-gcp.sh all
./deploy-gcp.sh api
```

The script builds the image, pushes to Artifact Registry, and creates/updates the Cloud Run service with the correct flags.

---

## 4. Environment Variables

| Key | Description | Required by |
|-----|-------------|-------------|
| `MONGODB_URI` | Atlas SRV string | all |
| `JWT_SECRET` | Auth token signing secret | api, worker |
| `STRIPE_SECRET_KEY` | Live key | api |
| `OPENAI_API_KEY` | For AI features | worker |
| `APP_ENV` | `production` / `staging` | all |
| `FRONTEND_URL` | Public FE URL | api (CORS) |

### 4.1 Secure Storage

Prefer **Secret Manager** over `.env` files in production:

```
# create
echo -n "super-secret" | gcloud secrets create jwt-secret --data-file=-

# grant runtime SA access
gcloud secrets add-iam-policy-binding jwt-secret \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
```

Pass secrets to Cloud Run via the `--set-secrets` flag in `deploy-gcp.sh`.

---

## 5. MongoDB Atlas Setup

Detailed steps are mirrored in `MONGODB_ATLAS_SETUP.md`; quick version:

1. **Create Cluster**: Shared M0 → Region close to GCP region.
2. **Network Access** → IP Access List  
   - Add `0.0.0.0/0` temporarily **only** for initial connection,  
     then replace with [Cloud Run egress IP ranges](https://cloud.google.com/compute/docs/faq#find_ip_range).
3. **Database Access** → Add DB user  
   - Role: *Atlas Admin* (or custom w/ readWriteAnyDatabase)
4. **Get Connection URI** (`mongodb+srv://<user>:<pass>@cluster.xxxx.mongodb.net/app?retryWrites=true&w=majority`)  
   Store as **Secret** `MONGODB_URI`.

---

## 6. Google Cloud Setup

### 6.1 Enable APIs

```
gcloud services enable run.googleapis.com \
      cloudbuild.googleapis.com \
      artifactregistry.googleapis.com \
      secretmanager.googleapis.com
```

### 6.2 Artifact Registry

```
gcloud artifacts repositories create pcc-repo \
    --repository-format=docker --location=us-central1
```

### 6.3 Runtime Service Account

```
gcloud iam service-accounts create pcc-runner \
    --display-name "PCC Cloud Run SA"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:pcc-runner@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/run.admin"
```

---

## 7. Deployment Steps

### 7.1 Clone & Configure

```
git clone https://github.com/Margot-mpart/PrivateClient4.git
cd PrivateClient4
cp .env.example .env              # fill local values for test
```

### 7.2 Build & Push (all services)

```
chmod +x deploy-gcp.sh
./deploy-gcp.sh all \
  --project=my-gcp-project \
  --region=us-central1 \
  --repo=pcc-repo
```

Flags default to env values inside the script. Override as needed.

### 7.3 Verify

```
gcloud run services list
gcloud run services describe pcc-api --format='value(status.url)'
```

Open the FE URL in browser, sign-up flow should succeed and ping the API.

---

## 8. Custom Domain & HTTPS

1. **Reserve Mapping**

```
gcloud run domain-mappings create --service=pcc-fe \
   --domain=app.yourdomain.com --region=us-central1
```

2. **Update DNS**  
   Add the TXT + A/AAAA records displayed in the command output.

3. **Managed Certificate** will auto-issue; provisioning can take up to 30 min.

4. **Force HTTPS**  
   Cloud Run enforces HTTPS automatically. Make sure your FE code uses `https://`.

---

## 9. CI/CD (optional)

The repository includes `cloudbuild.yaml`.  
Create a trigger that fires on `main` branch pushes:

```
gcloud builds triggers create github \
   --repo-name=PrivateClient4 \
   --repo-owner=Margot-mpart \
   --branch-pattern="^main$" \
   --build-config=cloudbuild.yaml
```

---

## 10. Rollback & Traffic Splits

Cloud Run keeps the last 100 revisions.

```
gcloud run services update-traffic pcc-api \
   --to-revisions=rev1=100 --region=us-central1
```

Canary:

```
gcloud run services update-traffic pcc-fe \
   --to-revisions=rev3=10,rev2=90
```

---

## 11. Troubleshooting

| Symptom | Fix |
|---------|-----|
| 502 errors | Check env vars, DB auth, `gcloud run logs tail` |
| `ECONNREFUSED` to Mongo | Whitelist egress IP range in Atlas |
| Stripe webhooks fail | Add HTTPS URL in Stripe dashboard |
| Certificate pending | Ensure DNS records are correct; wait 30 min |

---

## 12. Next Steps

* Set up **Observability**: Cloud Run metrics + Error Reporting
* Consider **Cloud CDN** in front of FE for caching.
* Use **Terraform** in `infra/` for repeatable environments (dev/staging/prod).

---

### References

* deploy-gcp.sh – one-click deploy
* MONGODB_ATLAS_SETUP.md – in-depth DB guide
* PLATFORM_OVERVIEW.md – functional documentation
* Google Cloud Run Docs – https://cloud.google.com/run/docs
* MongoDB Atlas Docs – https://www.mongodb.com/docs/atlas

Happy shipping! 🚀
