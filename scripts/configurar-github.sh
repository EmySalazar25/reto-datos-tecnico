#!/usr/bin/env bash
# Configura en GitHub la frontera de aprobación humana del estándar. Los environments, las
# reglas de protección y los secrets NO se copian al hacer fork: este script los recrea.
#
#   scripts/configurar-github.sh [owner/repo] [revisor1,revisor2]
#
# Requiere `gh` autenticado con permisos de administración del repositorio. Por omisión usa el
# repo actual y a la persona autenticada como revisora. Las reglas de environments con
# revisores y la protección de rama requieren un repositorio público (o un plan de pago).
set -euo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
REVISORES="${2:-$(gh api user --jq .login)}"

echo "Repositorio: $REPO"
echo "Revisores:   $REVISORES"

reviewers_json() {
  local items=() id
  IFS=',' read -ra logins <<< "$REVISORES"
  for login in "${logins[@]}"; do
    id=$(gh api "users/$login" --jq .id)
    items+=("{\"type\":\"User\",\"id\":$id}")
  done
  local joined
  joined=$(IFS=','; echo "${items[*]}")
  echo "[$joined]"
}

REVIEWERS=$(reviewers_json)

crear_environment() {
  local nombre="$1" descripcion="$2"
  echo "- environment '$nombre': $descripcion"
  # prevent_self_review=false permite que una sola persona apruebe en este repo de demostración;
  # en un equipo debe ser true (quien solicita no aprueba).
  gh api -X PUT "repos/$REPO/environments/$nombre" --input - <<JSON >/dev/null
{"wait_timer": 0, "prevent_self_review": false, "reviewers": $REVIEWERS, "deployment_branch_policy": null}
JSON
}

crear_environment aprobacion-estandar "cambios que debilitan el estándar o rompen un contrato (GOV-07)"
crear_environment produccion-destructiva "full-refresh y recreación de tablas publicadas"

echo "- protección de la rama main"
gh api -X PUT "repos/$REPO/branches/main/protection" --input - <<'JSON' >/dev/null
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["herramientas (3.9)", "herramientas (3.13)", "secretos", "certificacion", "aprobacion"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON

echo
echo "Listo. Verifica en Settings → Environments y Settings → Branches."
echo "Si administras el estándar en un fork, actualiza el usuario en .github/CODEOWNERS."
