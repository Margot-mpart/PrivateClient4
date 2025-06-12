# MongoDB Atlas Setup Guide  
Connecting the PCC Platform (FastAPI/React) from Google Cloud Run
---

> Estimated time: **20 minutes** (excluding data migration)

---

## 1. Create / Log-in to MongoDB Atlas

1. Go to <https://www.mongodb.com/cloud/atlas>.
2. Choose **Free Tier** (M0) for dev ➜ upgrade later.
3. Pick **Organization ► Project** structure:  
   `Org: PCC` → `Project: production`.

---

## 2. Build Your First Cluster

| Option | Recommended |
|--------|-------------|
| Cloud Provider | **GCP** (match Cloud Run region) |
| Region | Same as Cloud Run, e.g. `us-central1` |
| Cluster Tier | M0 (Shared) for staging, M10+ for prod |
| Name | `pcc-prod` |

Click **Create Cluster** – provisioning takes ~2-5 min.

---

## 3. Database Users (Authentication)

1. Atlas ► *Database Access* ► **Add New Database User**  
2. Select **Username/Password**, e.g.  
   ```
   user: pcc_service
   pass: <GENERATE>        # store in password manager
   ```
3. **Database User Privileges**  
   *Production*: `Read and write to any database`  
   *Limited*: custom role mapping to `pcc` DB only.
4. **Add User**.

Keep the credentials—will be supplied to Cloud Run via Secret Manager.

---

## 4. Network Access (IP Whitelist)

### 4.1 Quick Dev Access

*Temporary* – allow your workstation:

```
My IP  203.0.113.5/32
```

### 4.2 Cloud Run Egress IP Ranges (Prod)

Cloud Run uses large, region-specific egress blocks.

1. Retrieve CIDR list:  
   ```
   gcloud compute addresses list --global | grep run
   ```
2. Add each CIDR `/20` range under **Network Access ► IP Access List**.  
   Annotate entry: `gcp-us-central1-cloud-run`.

Alternatively, enable **VPC Peering** (preferred for strict security) — requires paid cluster. Skip for M0.

---

## 5. Obtain the Connection URI

Atlas ► *Clusters* → **Connect** → *Drivers*.

Copy the SRV URI:

```
mongodb+srv://pcc_service:<PASSWORD>@pcc-prod.n1xx.mongodb.net/pcc?retryWrites=true&w=majority
```

Replace `<PASSWORD>` placeholder if storing directly; otherwise keep as secret.

---

## 6. Store Secrets in Google Secret Manager

```
echo -n 'mongodb+srv://pcc_service:******@pcc-prod.n1xx.mongodb.net/pcc?retryWrites=true&w=majority' \
  | gcloud secrets create mongodb-uri --data-file=- --replication-policy=automatic

gcloud secrets add-iam-policy-binding mongodb-uri \
  --member="serviceAccount:pcc-runner@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

In `deploy-gcp.sh`:

```
--set-secrets=MONGODB_URI=mongodb-uri:latest
```

---

## 7. FastAPI Configuration

`app/core/config.py` (already in repo):

```python
from functools import lru_cache
from pydantic import AnyUrl, Field, BaseSettings

class Settings(BaseSettings):
    mongodb_uri: AnyUrl = Field(..., env="MONGODB_URI")
    # ...

@lru_cache
def get_settings():
    return Settings()
```

No code changes needed once `MONGODB_URI` env var is injected by Cloud Run.

---

## 8. Data Migration & Seed

### 8.1 Initial Schema (FastAPI models)

FastAPI + Motor (async driver) creates collections on first write; no SQL-style migrations needed.

### 8.2 Import Existing Data

If migrating from local Mongo:

```
# Dump local DB
mongodump --uri="mongodb://localhost:27017/pcc" --out=dump/

# Restore to Atlas
mongorestore --uri="$MONGODB_URI" dump/pcc
```

For large datasets, compress and use `--gzip`.

### 8.3 Seed Admin Account (optional)

Run the included script:

```
python scripts/seed_admin.py --email "admin@pcc.com"
```

---

## 9. Automated Backups

Free tiers (M0–M2) provide **daily snapshots** (3-day retention).  
Upgrade to **M10** for point-in-time backups.

---

## 10. Monitoring & Alerts

1. Atlas ► *Alerts* → out-of-box CPU, memory, auto-scaling.
2. Integrations: Slack, Email, Datadog.
3. **Metrics** tab shows query latency & connections—use to fine-tune connection pool size in FastAPI `motor.AsyncIOMotorClient`.

---

## 11. Costs & Scaling Checklist

| Stage | Tier | Notes |
|-------|------|-------|
| Dev / QA | M0 | free, 512 MB RAM, 100 conns |
| Staging | M2 | \$9/mo |
| Production | M10+ | auto-scales storage & memory |

Plan upgrade before hitting 80 % limits (Atlas email alert).

---

## 12. Troubleshooting

| Issue | Resolution |
|-------|------------|
| `(AuthFailed)` | Verify DB user, IP allow list. |
| `ECONNREFUSED` from Cloud Run | Egress range missing in Atlas network whitelist. |
| High connection usage | Reduce connection pool (`MAX_POOL_SIZE`), enable connection pooling in Motor. |
| Slow queries | Create indexes via Atlas Performance Advisor. |

---

## 13. Next Steps

* Enable **Database Triggers** for real-time events.
* Configure **Data API** if exposing read-only endpoints.
* Adopt **Terraform** module in `infra/terraform/mongodb` for declarative setup.

---

### References

* Atlas Docs – <https://www.mongodb.com/docs/atlas/>
* GCP-to-Atlas connectivity – <https://www.mongodb.com/docs/atlas/security/#google-cloud-platform>
* Motor Driver – <https://motor.readthedocs.io>
