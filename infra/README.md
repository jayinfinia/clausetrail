# Deployment

Compose builds a single app image (React + FastAPI + OCR) and a private PostgreSQL service. App traffic is bound to host loopback. Local named volumes preserve original demo files and database state. No cloud resources are provisioned.

Production infrastructure and identity are out of scope for this build; docs/PRODUCTION.md lists what a deployment needs.
