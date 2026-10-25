#!/bin/sh
# Activa los hooks versionados de este clon (.githooks) y comprueba que el escáner está disponible. Se ejecuta una vez por clon.
set -eu
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
git config core.hooksPath .githooks
chmod +x .githooks/* security/*.sh 2> /dev/null || true
echo "core.hooksPath = $(git config core.hooksPath)"
if security/scan.sh history > /dev/null 2>&1; then
  echo "OK: Gitleaks corre y el historial de este clon está limpio con la configuración del monorepo"
else
  echo "AVISO: Gitleaks no corrió limpio (¿falta el binario o hay un hallazgo?). Mira: security/scan.sh history" >&2
  exit 1
fi
if sh security/selftest.sh > /dev/null 2>&1; then
  echo "OK: la autoprueba pasa (el hook bloquea secretos falsos y deja pasar las plantillas)"
else
  echo "AVISO: la autoprueba falla. Mira: sh security/selftest.sh" >&2
  exit 1
fi
