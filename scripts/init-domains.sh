#!/usr/bin/env bash
set -euo pipefail

# Create 22 knowledge domain directories with sub-types
DOMAINS=(
    management transport finance production computing repair
    engineering construction science agriculture social administration
    legal sales education personal media healthcare care maintenance
    food security
)

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WIKI_DIR="$SCRIPT_DIR/wiki"

echo "Initializing $SCRIPT_DIR/wiki with ${#DOMAINS[@]} domains..."

for domain in "${DOMAINS[@]}"; do
    for subtype in concepts strategies anti-patterns; do
        dir="$WIKI_DIR/$domain/$subtype"
        mkdir -p "$dir"
        touch "$dir/.gitkeep"
    done
done

# Also ensure _shared
for subtype in concepts strategies anti-patterns; do
    dir="$WIKI_DIR/_shared/$subtype"
    mkdir -p "$dir"
    touch "$dir/.gitkeep"
done

echo "Done. ${#DOMAINS[@]} domains x 3 subtypes = $((${#DOMAINS[@]} * 3)) directories created."
