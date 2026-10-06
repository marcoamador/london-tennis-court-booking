#!/usr/bin/env sh
# Deploys a commit of origin/main. Run on the server, either by hand (./scripts/deploy.sh)
# or by GitHub Actions through an SSH key whose authorized_keys entry forces this command.
# The only input is the commit SHA (from SSH_ORIGINAL_COMMAND when forced); default: origin/main.
set -eu

# Everything lives in a function so the shell has read the whole script before `git checkout`
# can replace this file on disk.
main() {
  cd "${APP_DIR:-/opt/courtwatch}"

  ref="${SSH_ORIGINAL_COMMAND:-${1:-}}"
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
