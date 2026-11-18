#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$repo_root/deploy/hf_space"
rm -rf "$out"
mkdir -p "$out"
cp "$repo_root/Dockerfile" "$repo_root/.dockerignore" "$repo_root/pyproject.toml" "$out/"
cp -R "$repo_root/src" "$repo_root/ontology" "$out/"
mkdir -p "$out/demo"
rsync -a --exclude='__pycache__' "$repo_root/demo/" "$out/demo/"
mkdir -p "$out/demo/bundle"
cp -R "$repo_root/demo/bundle/." "$out/demo/bundle/"
cat > "$out/README.md" <<'EOF'
---
title: AU/NZ business graph
sdk: docker
app_port: 7860
---

# AU/NZ business graph

Docker Space for the Business Graph demo. The included trimmed bundle is tracked
with Git LFS using the rule in `.gitattributes`.
EOF
cat > "$out/.gitattributes" <<'EOF'
demo/bundle/** filter=lfs diff=lfs merge=lfs -text
EOF
