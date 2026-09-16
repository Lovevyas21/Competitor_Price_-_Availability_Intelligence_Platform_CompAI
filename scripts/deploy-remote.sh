#!/usr/bin/env bash
# Runs *on the EC2 host*, as root, via SSM. Driven by `scripts/aws.sh deploy`.
#
# The image is built here rather than pushed from a workstation because the host is
# Graviton: an image built on x86 will not start on arm64, and cross-building under QEMU
# on a small machine is slower than building natively on the target.
#
# Idempotent. Re-running it re-fetches source, rebuilds, re-migrates and restarts; every
# step is safe to repeat, which is what makes a half-finished deploy recoverable by
# running the same command again.
set -euo pipefail

# Say which step died, on the way out. `set -e` stops at the first failure but prints
# nothing about where, and the interesting part of a 150-line deploy log is precisely
# which of nine steps it stopped at.
STEP="starting up"
trap 'rc=$?; [ $rc -ne 0 ] && echo "=== DEPLOY FAILED during: $STEP (exit $rc) ===" >&2; exit $rc' EXIT

REGION="${REGION:-ap-south-1}"
PROJECT="${PROJECT:-cpi}"
SRC=/srv/cpi/src

ACCOUNT=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
BUCKET="${PROJECT}-bronze-${ACCOUNT}"
ECR="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${PROJECT}"

log() { STEP="$*"; echo "=== $* ==="; }

log "fetching source"
aws s3 cp "s3://${BUCKET}/deploy/cpi-src.tar.gz" /tmp/src.tar.gz --region "$REGION" --quiet
rm -rf "$SRC" && mkdir -p "$SRC"
tar -xzf /tmp/src.tar.gz -C "$SRC"

log "fetching secrets from SSM"
/usr/local/bin/cpi-fetch-env
# .env.static is written by user_data at boot: bronze bucket and environment name.
cat /srv/cpi/.env.static >> /srv/cpi/.env
chmod 600 /srv/cpi/.env
echo "parameters loaded: $(wc -l < /srv/cpi/.env)"

log "building image (native arm64)"
cd "$SRC"
docker build -t "${PROJECT}:latest" . 2>&1 | tail -5

log "pushing to ECR"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ECR" >/dev/null 2>&1
docker tag "${PROJECT}:latest" "${ECR}:latest"
docker push "${ECR}:latest" 2>&1 | tail -3

log "running migrations"
docker run --rm --env-file /srv/cpi/.env "${PROJECT}:latest" alembic upgrade head 2>&1 | tail -8

log "building marts"
# DBT_PROFILES_DIR is how profiles.yml is found; the image carries dbt/ at /app/dbt.
#
# `dbt deps` first: the image carries dbt/ but deliberately not dbt_packages/, so
# dbt_utils has to be fetched here. Without it `dbt build` fails at compile time with a
# message about missing packages rather than anything to do with the warehouse.
#
# Both commands in one container, so the packages downloaded by `deps` are still present
# for `build` -- a second `docker run` starts from a clean layer and loses them.
docker run --rm --env-file /srv/cpi/.env -e DBT_PROFILES_DIR=/app/dbt \
  -w /app/dbt "${PROJECT}:latest" \
  sh -c 'dbt deps && dbt build' 2>&1 | tail -25

log "starting the stack"
cd "$SRC"
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile workers up -d 2>&1 | tail -10

log "status"
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile workers ps

log "health"
# The API needs a moment to bind before it answers.
sleep 8
curl -fsS http://localhost:8000/health || echo "health check did not answer yet"
