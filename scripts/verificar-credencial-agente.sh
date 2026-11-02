#!/usr/bin/env bash
# Verifica qué puede y qué no puede hacer la credencial de GitHub con la que corre el agente.
# Pensado para correr dentro del contenedor, con el token del agente:
#
#   read -rs DP_AGENTE_GH_TOKEN && export DP_AGENTE_GH_TOKEN     # no queda en el historial
#   docker compose run --rm dp scripts/verificar-credencial-agente.sh
#
# Cada sonda es inocua: usa una corrida, una rama, un PR o una referencia que no existen, o un
# push que GitHub debe rechazar (si lo aceptara, la rama se borra en el acto). Nunca imprime el
# token. Sale con 1 si la credencial puede cruzar la frontera humana: aprobar environments,
# administrar la protección, disparar workflows o modificar el CI.
#
#   --sin-sonda-ci   omite el push de prueba (para revisar una credencial completa sin efectos)
set -uo pipefail

SONDA_CI=1
[ "${1:-}" = "--sin-sonda-ci" ] && { SONDA_CI=0; shift; }
REPO="${1:-$(git remote get-url origin 2>/dev/null | sed -E 's#^(https://github.com/|git@github.com:|ssh://git@github.com/)##; s#\.git$##')}"
[ -n "$REPO" ] || { echo "no se pudo determinar el repositorio: pásalo como argumento (owner/repo)"; exit 2; }

if ! gh api user --silent >/dev/null 2>&1; then
  echo "Repositorio: $REPO"
  [ -n "${GH_TOKEN:-}" ] && echo "GH_TOKEN está definido, pero GitHub no lo acepta (inválido o expirado)."
  echo "Credencial:  ninguna. El agente no puede empujar ramas ni abrir PRs, y tampoco cruzar la"
  echo "frontera humana. Para que abra el PR con el fix, dale un token de grano fino (ver README)."
  exit 0
fi

case "${GH_TOKEN:-}" in
  github_pat_*) TIPO="token de grano fino (GH_TOKEN)" ;;
  ghp_*|gho_*)  TIPO="token clásico (GH_TOKEN): no se puede limitar por permiso; usa uno de grano fino" ;;
  "")           TIPO="sesión de gh de esta máquina (sin GH_TOKEN)" ;;
  *)            TIPO="token de tipo desconocido (GH_TOKEN)" ;;
esac
CUENTA=$(gh api user --jq .login 2>/dev/null || echo "sin credencial")
echo "Repositorio: $REPO"
echo "Credencial:  $TIPO · cuenta $CUENTA"
echo

codigo() {  # método ruta [campos de gh api...] → código HTTP de la respuesta
  local metodo="$1" ruta="$2"; shift 2
  gh api -X "$metodo" "$ruta" "$@" --include 2>/dev/null | head -1 | awk '{print $2}'
}

CRUZA=0
fila() {  # capacidad, ¿debe poder? (si|no), código, códigos que significan "puede"
  local capacidad="$1" debe="$2" cod="$3" puede_si="$4" resultado
  if [[ " $puede_si " == *" $cod "* ]]; then resultado="PUEDE"
  elif [ "$cod" = 403 ] || [ "$cod" = 404 ]; then resultado="NO PUEDE"
  else resultado="INDETERMINADO"; fi
  local marca="✓"
  if [ "$debe" = no ] && [ "$resultado" != "NO PUEDE" ]; then marca="✗"; CRUZA=1; fi
  if [ "$debe" = si ] && [ "$resultado" != "PUEDE" ]; then marca="!"; fi
  printf '%s %-40s %-14s (HTTP %s)\n' "$marca" "$capacidad" "$resultado" "${cod:-—}"
}

echo "Trabajar (el agente debe poder):"
fila "leer el repositorio" si "$(codigo GET "repos/$REPO")" "200"
if GIT_TERMINAL_PROMPT=0 git push --dry-run -q origin "HEAD:refs/heads/sonda-credencial-$$" >/dev/null 2>&1; then
  fila "empujar ramas" si 200 "200"
else
  fila "empujar ramas" si 403 "200"
fi
fila "abrir PRs" si "$(codigo POST "repos/$REPO/pulls" -f title=sonda -f head=__sonda_no_existe__ -f base=main)" "422"
fila "fusionar un PR con checks en verde" si "$(codigo PUT "repos/$REPO/pulls/999999999/merge")" "404 422"

echo
echo "Cruzar la frontera humana (el agente NO debe poder):"
fila "aprobar un environment" no \
  "$(codigo POST "repos/$REPO/actions/runs/1/pending_deployments" -F 'environment_ids[]=1' -f state=approved -f comment=sonda)" "404 422"
fila "disparar un workflow (destructivo)" no \
  "$(codigo POST "repos/$REPO/actions/workflows/destructivo.yml/dispatches" -f ref=__sonda_no_existe__)" "422 204"
fila "leer o cambiar la protección de main" no "$(codigo GET "repos/$REPO/branches/main/protection")" "200"

if [ "$SONDA_CI" = 1 ]; then
  rama="sonda-ci-$$"
  dir=$(mktemp -d)
  git worktree add -q --detach "$dir" HEAD
  echo "# sonda de credencial" >> "$dir/.github/workflows/ci.yml"
  git -C "$dir" -c user.name=sonda -c user.email=sonda@example.invalid commit -qam "sonda de credencial"
  if GIT_TERMINAL_PROMPT=0 git -C "$dir" push -q origin "HEAD:refs/heads/$rama" >/dev/null 2>&1; then
    GIT_TERMINAL_PROMPT=0 git push -q origin --delete "$rama" >/dev/null 2>&1
    fila "modificar el CI (.github/workflows)" no 200 "200"
  else
    fila "modificar el CI (.github/workflows)" no 403 "200"
  fi
  git worktree remove --force "$dir"
fi

echo
if [ "$CRUZA" = 1 ]; then
  echo "RESULTADO: esta credencial puede cruzar la frontera humana. No se la des al agente."
  exit 1
fi
echo "RESULTADO: la credencial trabaja, pero no puede aprobar, administrar, disparar workflows ni tocar el CI."
echo "Límite: con Contents (write) puede fusionar un PR cuyos checks requeridos pasen. Un cambio"
echo "gobernado sigue necesitando tu aprobación en el environment (check \`aprobacion\`)."
