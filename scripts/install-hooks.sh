#!/bin/sh
# Installs the repo's git hooks into this clone. Run once per computer:  sh scripts/install-hooks.sh
# (Git doesn't copy hooks when you clone, which is why they are kept in scripts/git-hooks/ and installed by hand.)
set -e
cd "$(git rev-parse --show-toplevel)"
cp scripts/git-hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
echo "Installed: .git/hooks/pre-push (the secret scanner now runs before every push)"
