#!/usr/bin/env sh
# Deploys a commit of origin/main. Run on the server: by hand (./scripts/deploy.sh [sha]), by
# GitHub Actions over SSH as `.../scripts/deploy.sh <sha>`, or through an SSH key whose
# authorized_keys entry forces this command. The only input is the commit SHA; for a forced key it
# is the last word of the requested command (nothing else in it is ever executed).
# Default: origin/main.
set -eu

# Everything lives in a function so the shell has read the whole script before `git checkout`
# can replace this file on disk.
main() {
  # The checkout this script lives in (override with APP_DIR).
  cd "${APP_DIR:-$(dirname "$0")/..}"

  ref="${1:-}"
  if [ -n "${SSH_ORIGINAL_COMMAND:-}" ]; then
    ref="${SSH_ORIGINAL_COMMAND##* }"
  fi
  case "$ref" in
    "") ref="origin/main" ;;
    *[!0-9a-f]*) echo "Refusing: expected a commit SHA, got '$ref'" >&2; exit 2 ;;
  esac

  echo "==> Fetching"
  git fetch --prune origin main
  if [ "$ref" != "origin/main" ] && ! git merge-base --is-ancestor "$ref" origin/main; then
    echo "Refusing: $ref is not on origin/main" >&2
    exit 2
  fi

  echo "==> Checking out $ref"
  # .env, Docker volumes and backups/ are untracked/ignored, so they survive this.
  git checkout --quiet --detach "$ref"

  echo "==> Building and restarting"
  docker compose up -d --build --remove-orphans
  docker image prune -f >/dev/null

  echo "==> Deployed $(git rev-parse --short HEAD)"
}

main "$@"
