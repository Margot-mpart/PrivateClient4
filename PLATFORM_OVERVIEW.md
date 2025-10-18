# PCC Platform – Comprehensive Overview

Private Client Consultants (PCC) is a Kajabi-style SaaS that enables professional coaches and consultants to sell courses, manage clients, and deliver AI-powered sessions in one secure cloud platform.

---

## 1. Vision & Core Value Proposition
* **All-in-one workspace** – scheduling, video sessions, course delivery, payments.
* **AI-assisted coaching** – automatic transcription, sentiment & topic analysis, action-item extraction.
* **Scalable multi-tenant architecture** – each coach operates an isolated “space” while sharing common infrastructure.
* **Pay-as-you-grow** – usage-based billing driven by Stripe metered products.

---

## 2. High-Level Architecture

```
Browser ── HTTPS ──► Cloud Run (Frontend – React/Vite)
                           │ REST / WS
                           ▼
                   Cloud Run (API – FastAPI)
                           │ Async Driver (Motor)
                           ▼
                 MongoDB Atlas (Shared Cluster)
                           │ PubSub / Webhook events
                           ▼
                   Cloud Run (Worker – Celery/FastAPI)
```

* **Containers**: Three independent Docker images (frontend, api, worker) deployed to Cloud Run.
* **State**: Single MongoDB Atlas cluster (multi-project). Collections are logically separated by tenant-ID.
* **CI/CD**: Cloud Build + Artifact Registry. `main` branch auto-deploys to production.

---

## 3. Technology Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| Frontend | **React 18**, Vite, TypeScript, Tailwind CSS | PWA, offline caching |
| API | **FastAPI** (Py 3.11), Pydantic v2, Uvicorn | Async endpoints (ASGI), JWT auth |
| Worker | FastAPI tasks + **Celery** | Redis (Cloud Memorystore) optional for high throughput |
| DB | **MongoDB Atlas** | SRV connection via Secret Manager |
| Payments | **Stripe** | Webhooks handled by API |
| AI / NLP | **OpenAI GPT-4** via openai-python | Pluggable for Azure/OpenAI |
| Cloud | **Google Cloud Platform** | Cloud Run, Artifact Registry, Secret Manager, Cloud Build |

---

## 4. Module Breakdown

### 4.1 Frontend (apps/frontend)
* React Router v6, Zustand state.
* Auth flow: magic-link email → JWT stored in httpOnly cookie.
* Role-based UI (Coach vs. Client).
* Embedded video powered by daily.co (can swap for Google Meet).

### 4.2 API Service (apps/api)
* FastAPI routers grouped by **auth**, **courses**, **sessions**, **billing**, **admin**.
* Dependency-override pattern for clean testing.
* Async Mongo access through Motor; automatic index creation on startup.
* Background tasks delegated to Worker via Celery/RabbitMQ (optional).

### 4.3 Worker Service (apps/worker)
* Processes heavy jobs: transcript analysis, pdf generation, email drip campaigns.
* Exposes health endpoint for Cloud Run autoscaler.

---

## 5. Data Model Catalogue (excerpt)

| Collection | Key Fields | Purpose |
|------------|-----------|---------|
| `users` | `email`, `role`, `hashed_pw`, `stripe_customer_id` | Coaches & clients (role enum) |
| `coaches` | `user_id`, `bio`, `industry`, `pricing_plan` | Coach-specific metadata |
| `clients` | `user_id`, `coach_id`, `goal`, `tags[]` | Client profile & segmentation |
| `sessions` | `coach_id`, `client_id`, `start`, `duration`, `video_url` | Live or recorded sessions |
| `transcripts` | `session_id`, `language`, `status`, `words[]` | Raw Otter/Whisper output |
| `analysis` | `session_id`, `summary`, `sentiment`, `action_items[]` | GPT-4 derived insights |
| `courses` | `coach_id`, `title`, `modules[]`, `price` | Digital products |
| `enrollments` | `course_id`, `client_id`, `progress%` | Course tracking |
| `payments` | `stripe_payment_intent`, `amount`, `currency`, `status` | Billing records |
| `crm_notes` | `client_id`, `author_id`, `note`, `created_at` | Coach CRM |

> Total: **40+ Pydantic models** in `app/schemas/`. All inherit from a common `BaseModel` with `tenant_id`.

---

## 6. Integrations

| Service | Integration Point | Usage |
|---------|------------------|-------|
| **MongoDB Atlas** | Async Motor client | Primary datastore |
| **Stripe** | Webhooks `/billing/stripe/webhook` | Payments, metering, subscriptions |
| **OpenAI** | Worker task `analyze_transcript` | Summaries, coaching tips |
| **SendGrid** | `email_service.send()` helper | Transactional & marketing emails |
| **Secret Manager** | All sensitive env vars | No secrets in code / Docker layers |
| **Cloud Logging** | `structlog + google-cloud-logging` | Centralized JSON logs |
| **Cloud Trace** | OpenTelemetry | Distributed tracing across Run services |

---

## 7. Security Posture

* **JWT** with rotating signing key (loaded from Secret Manager).
* **CORS** locked to `FRONTEND_URL`.
* **Helmet-style headers** served by FastAPI middleware.
* **OWASP** tests in CI (pytest-zap plugin).
* PCI-DSS scope reduced—card details handled only by Stripe Elements.

---

## 8. Scalability & Performance

* Cloud Run **minInstance=0** for cost; API keeps **min=1** in prod.
* Horizontal scaling by concurrent requests; stateless containers.
* MongoDB connection pool adjusted per instance (env `MAX_POOL_SIZE`).
* Caching layer (Cloud Memorystore Redis) optional for heavy dashboards.

---

## 9. Observability

* **gcloud run logs tail –service=pcc-api** for structured logs.
* **Prometheus** exporter endpoint (`/metrics`) behind auth.
* **Sentry** DSN configurable for FE & API.

---

## 10. Roadmap

| Milestone | Status |
|-----------|--------|
| Multi-currency billing | ️⬜ |
| Native iOS / Android shell | ⬜ |
| SCIM provisioning for enterprise plans | ⬜ |
| Terraform modules for all GCP + Atlas | ⬜ |

---

## 11. Repository Map

```
root
 ├── apps/
 │   ├── api/          # FastAPI service
 │   ├── frontend/     # React app
 │   └── worker/       # Celery tasks
 ├── docker/           # Dockerfiles
 ├── deploy-gcp.sh     # ☁️ one-click deploy
 ├── DEPLOYMENT_GUIDE.md
 ├── MONGODB_ATLAS_SETUP.md
 └── infra/terraform/  # optional IaC
```

---

### Contact

For architecture questions: **dev@pcc-platform.com**  
For security reports: **security@pcc-platform.com** (PGP key available)

_© 2025 PCC Platform. All rights reserved._
