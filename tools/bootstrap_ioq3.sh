#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d .git ]]; then
  echo "Run from the halo-arena repository root." >&2
  exit 1
fi

if git remote get-url ioq3 >/dev/null 2>&1; then
  echo "ioq3 remote already exists."
else
  git remote add ioq3 https://github.com/ioquake/ioq3.git
fi

git fetch ioq3 main

echo
echo "ioq3 upstream is now available as ioq3/main."
echo "Recommended first import:"
echo "  git merge --allow-unrelated-histories ioq3/main"
echo
echo "Review the merge before pushing."
