#!/bin/sh
# Use the repository's git hooks (tools/git-hooks). Run once per clone.
# The pre-commit hook keeps slide pictures and their source files in step.
set -e
root=$(git rev-parse --show-toplevel)
chmod +x "$root/tools/git-hooks/"*
git -C "$root" config core.hooksPath tools/git-hooks
echo "Git hooks enabled (core.hooksPath = tools/git-hooks)."
