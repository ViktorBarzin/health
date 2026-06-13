# Oura scheduled-pull CronJob (infra stub — HITL)

The Connection framework (ADR-0006, BYOT variant) ships with a working
scheduled-pull **command**; the Kubernetes manifest that runs it on a cadence is
infrastructure (GitOps via Terraform/Terragrunt) and is **left for a human to
add** — this note is the spec.

## What runs

```
python -m app.services.connection_sync_cli
```

`run_scheduled_sync()` opens a DB session, builds the credential cipher from
`CONNECTION_ENCRYPTION_KEY`, and calls `sync_all_active`, which pulls **every
`active` Connection** independently (one failure never aborts the others) and
lands new samples idempotently via the existing dedup. It is safe to run as often
as you like — a re-pull of already-ingested nights inserts nothing. It exits
doing nothing if no encryption key is configured (fail closed).

This command is tested (`backend/tests/test_connection_sync_cli.py`); only the
manifest below is deferred.

## CronJob shape (to be added to the health stack)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: health-connection-sync
  namespace: health
spec:
  schedule: "0 * * * *"          # hourly — daily recovery data needs no faster
  concurrencyPolicy: Forbid       # don't overlap runs
  jobTemplate:
    spec:
      backoffLimit: 1
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: connection-sync
              image: viktorbarzin/health:latest   # same image as the app
              command: ["python", "-m", "app.services.connection_sync_cli"]
              env:
                - name: DATABASE_URL
                  valueFrom: { secretKeyRef: { name: health-db, key: url } }
                - name: CONNECTION_ENCRYPTION_KEY
                  # Vault secret/health-connection-key — the SAME key the app
                  # uses to decrypt each user's stored token. Wire via the
                  # existing Vault→env mechanism the app already uses.
                  valueFrom: { secretKeyRef: { name: health-connection-key, key: key } }
```

## Key management

`CONNECTION_ENCRYPTION_KEY` is a URL-safe base64 32-byte Fernet key. Generate one:

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store it in Vault (`secret/health-connection-key`) and inject it into **both** the
app Deployment and this CronJob — the CronJob must use the same key to decrypt the
tokens the app encrypted. To rotate, set the value to a comma-separated list with
the new key first (`new,old`): new writes use the new key, old ciphertext still
decrypts (MultiFernet — see `backend/app/services/crypto.py`).
