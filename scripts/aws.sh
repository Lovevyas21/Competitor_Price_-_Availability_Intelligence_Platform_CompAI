#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
PROJECT="${PROJECT:-cpi}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EPHEMERAL="$ROOT/infra/ephemeral"
PERSISTENT="$ROOT/infra/persistent"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m  ok\033[0m  %s\n' "$*"; }
warn() { printf '\033[33m  !!\033[0m  %s\n' "$*"; }
step() { printf '\n\033[36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }

need() {
  command -v "$1" >/dev/null || { echo "missing required tool: $1" >&2; exit 1; }
}
need terraform
need aws

account() { aws sts get-caller-identity --query Account --output text; }

cmd_status() {
  local acct; acct="$(account)"
  bold "account $acct  region $REGION"

  step "Billable compute"
  local ec2 rds
  ec2=$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Name,Values=${PROJECT}-app" \
              "Name=instance-state-name,Values=running,pending,stopping,stopped" \
    --query "Reservations[].Instances[].[InstanceId,State.Name,InstanceType]" \
    --output text 2>/dev/null || true)
  rds=$(aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier "${PROJECT}-pg" \
    --query "DBInstances[0].[DBInstanceStatus,DBInstanceClass]" \
    --output text 2>/dev/null || true)

  [ -n "$ec2" ] && warn "EC2: $ec2" || ok "EC2: none"
  [ -n "$rds" ] && warn "RDS: $rds" || ok "RDS: none"

  step "Charges that outlive a destroy"
  check_orphans

  step "Month to date"
  cost_so_far

  if [ -z "$ec2" ] && [ -z "$rds" ]; then
    echo
    ok "nothing billable is running beyond the persistent stack (~\$0.30/month)"
  else
    echo
    warn "compute is running -- roughly \$0.035/hour. './scripts/aws.sh down' stops it."
  fi
}

check_orphans() {
  local vols ips snaps
  vols=$(aws ec2 describe-volumes --region "$REGION" \
    --filters Name=status,Values=available \
    --query "Volumes[].[VolumeId,Size]" --output text 2>/dev/null || true)
  ips=$(aws ec2 describe-addresses --region "$REGION" \
    --query "Addresses[?AssociationId==null].[PublicIp]" --output text 2>/dev/null || true)
  snaps=$(aws rds describe-db-snapshots --region "$REGION" --snapshot-type manual \
    --query "DBSnapshots[?starts_with(DBSnapshotIdentifier,'${PROJECT}')].[DBSnapshotIdentifier]" \
    --output text 2>/dev/null || true)

  [ -n "$vols" ]  && warn "unattached EBS volumes: $vols" || ok "no unattached EBS volumes"
  [ -n "$ips" ]   && warn "unassociated Elastic IPs: $ips" || ok "no idle Elastic IPs"
  [ -n "$snaps" ] && warn "manual RDS snapshots: $snaps" || ok "no leftover RDS snapshots"
}

cost_so_far() {
  local start end
  start=$(date -u +%Y-%m-01)
  end=$(date -u -d tomorrow +%Y-%m-%d 2>/dev/null || date -u -v+1d +%Y-%m-%d)
  aws ce get-cost-and-usage \
    --time-period "Start=$start,End=$end" --granularity MONTHLY --metrics UnblendedCost \
    --group-by Type=DIMENSION,Key=SERVICE --region us-east-1 \
    --query "ResultsByTime[0].Groups[].[Keys[0],Metrics.UnblendedCost.Amount]" \
    --output text 2>/dev/null \
    | awk -F'\t' '$2+0 != 0 { printf "  %-45s $%.4f\n", $1, $2; t+=$2 }
                  END      { printf "  %-45s $%.4f\n", "TOTAL", t }' \
    || warn "Cost Explorer unavailable (it can take 24h to enable on a new account)"
}

cmd_up() {
  step "Persistent stack (bronze, ECR, secrets, budget)"
  terraform -chdir="$PERSISTENT" init -input=false >/dev/null
  terraform -chdir="$PERSISTENT" apply -input=false -auto-approve
  ok "persistent stack ready"

  step "Ephemeral stack (VPC, EC2, RDS) -- RDS takes most of the wait"
  terraform -chdir="$EPHEMERAL" init -input=false >/dev/null
  terraform -chdir="$EPHEMERAL" apply -input=false -auto-approve

  cmd_deploy
  echo
  bold "up."
  echo "  Nothing is published: the host has no open ports. Tunnel to it with"
  echo "    ./scripts/aws.sh open      then browse http://localhost:8000/docs"
  warn "this now costs ~\$0.035/hour. Run './scripts/aws.sh down' when finished."
}

cmd_deploy() {
  local bucket instance
  bucket="$(terraform -chdir="$PERSISTENT" output -raw bronze_bucket)"
  instance="$(terraform -chdir="$EPHEMERAL" output -raw app_instance_id)"

  step "Packaging source"
  local tarball; tarball="$(mktemp -t cpi-src-XXXXXX.tar.gz)"
  tar --exclude-vcs --exclude='./.venv' --exclude='./data' --exclude='__pycache__' \
      --exclude='*.pyc' --exclude='./.env' --exclude='./infra' --exclude='./dbt/target' \
      --exclude='./dbt/dbt_packages' --exclude='./.ruff_cache' --exclude='./.pytest_cache' \
      --exclude='./.claude' --exclude='./.agents' \
      -czf "$tarball" -C "$ROOT" .
  ok "$(du -h "$tarball" | cut -f1)"

  aws s3 cp "$tarball" "s3://${bucket}/deploy/cpi-src.tar.gz" --region "$REGION" --only-show-errors
  tr -d '\r' < "$ROOT/scripts/deploy-remote.sh" > "${tarball}.sh"
  aws s3 cp "${tarball}.sh" "s3://${bucket}/deploy/deploy.sh" \
    --region "$REGION" --only-show-errors
  rm -f "$tarball" "${tarball}.sh"
  ok "uploaded"

  step "Building and starting on the host"
  local cmd_id
  cmd_id=$(aws ssm send-command --region "$REGION" --instance-ids "$instance" \
    --document-name AWS-RunShellScript --timeout-seconds 3600 \
    --parameters "commands=[\"aws s3 cp s3://${bucket}/deploy/deploy.sh /root/deploy.sh --region ${REGION} --quiet\",\"bash /root/deploy.sh\"]" \
    --query "Command.CommandId" --output text)
  echo "  command $cmd_id"

  local status=""
  for _ in $(seq 1 60); do
    sleep 20
    status=$(aws ssm get-command-invocation --region "$REGION" \
      --command-id "$cmd_id" --instance-id "$instance" \
      --query Status --output text 2>/dev/null || echo Pending)
    printf '\r  %s          ' "$status"
    case "$status" in Success|Failed|Cancelled|TimedOut) break;; esac
  done
  echo

  aws ssm get-command-invocation --region "$REGION" \
    --command-id "$cmd_id" --instance-id "$instance" \
    --query StandardOutputContent --output text 2>/dev/null | tail -25

  [ "$status" = "Success" ] || { echo; warn "deploy ended as $status"; return 1; }
  ok "deployed"
}

cmd_open() {
  local instance; instance="$(terraform -chdir="$EPHEMERAL" output -raw app_instance_id)"
  command -v session-manager-plugin >/dev/null || {
    warn "the AWS session-manager-plugin is not installed -- the tunnel needs it"
    echo "  https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html"
    return 1
  }
  bold "forwarding localhost:8000 to the API. Ctrl-C to stop."
  echo "  http://localhost:8000/docs"
  echo "  http://localhost:8000/health"
  aws ssm start-session --region "$REGION" --target "$instance" \
    --document-name AWS-StartPortForwardingSession \
    --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
}

cmd_down() {
  step "Destroying the ephemeral stack"
  terraform -chdir="$EPHEMERAL" init -input=false >/dev/null
  terraform -chdir="$EPHEMERAL" destroy -input=false -auto-approve

  step "Verifying nothing billable survived"
  local ec2 rds
  ec2=$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Name,Values=${PROJECT}-app" \
              "Name=instance-state-name,Values=running,pending,stopping,stopped" \
    --query "Reservations[].Instances[].InstanceId" --output text 2>/dev/null || true)
  rds=$(aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier "${PROJECT}-pg" --query "DBInstances[0].DBInstanceStatus" \
    --output text 2>/dev/null || true)

  [ -z "$ec2" ] && ok "no EC2 instance" || warn "EC2 still present: $ec2"
  [ -z "$rds" ] && ok "no RDS instance" || warn "RDS still present: $rds"
  check_orphans

  echo
  bold "down. Remaining: bronze, ECR, secrets, budget alarm (~\$0.30/month)."
  echo "  Bring it back with './scripts/aws.sh up' -- the warehouse rebuilds from bronze."
}

cmd_nuke() {
  bold "This destroys the PERSISTENT stack as well."
  echo "  Bronze payloads, the image repository and the hand-entered API keys all go."
  echo "  The warehouse could not be rebuilt afterwards -- bronze is what it rebuilds from."
  echo
  read -r -p "Type 'destroy everything' to confirm: " reply
  [ "$reply" = "destroy everything" ] || { echo "cancelled"; exit 1; }

  cmd_down
  step "Emptying the bronze bucket"
  local bucket; bucket="$(terraform -chdir="$PERSISTENT" output -raw bronze_bucket)"
  python - "$bucket" "$REGION" <<'PY'
import subprocess, sys, json
bucket, region = sys.argv[1], sys.argv[2]
for key in ("Versions", "DeleteMarkers"):
    while True:
        out = subprocess.run(
            ["aws", "s3api", "list-object-versions", "--bucket", bucket,
             "--region", region, "--max-items", "500",
             "--query", f"{key}[].{{Key:Key,VersionId:VersionId}}", "--output", "json"],
            capture_output=True, text=True).stdout.strip()
        items = json.loads(out) if out and out != "null" else []
        if not items:
            break
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump({"Objects": items, "Quiet": True}, fh)
        subprocess.run(
            ["aws", "s3api", "delete-objects", "--bucket", bucket, "--region", region,
             "--delete", f"file://{path}"],
            capture_output=True, text=True)
        os.unlink(path)
        print(f"  removed {len(items)} {key.lower()}")
PY
  step "Destroying the persistent stack"
  terraform -chdir="$PERSISTENT" destroy -input=false -auto-approve
  bold "everything destroyed. The account should now bill nothing for this project."
}

case "${1:-status}" in
  up)     cmd_up ;;
  down)   cmd_down ;;
  deploy) cmd_deploy ;;
  open)   cmd_open ;;
  status) cmd_status ;;
  nuke)   cmd_nuke ;;
  *) echo "usage: $0 {up|down|deploy|open|status|nuke}" >&2; exit 2 ;;
esac
