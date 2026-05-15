#!/usr/bin/env bash
# Extract the body of a CHANGELOG section for a given version.
# Used by .github/workflows/release.yml to build the GitHub Release body.
#
# Usage:
#   scripts/extract_changelog.sh <version> [path]
#
# Example:
#   scripts/extract_changelog.sh 0.2.1 CHANGELOG.md
#   scripts/extract_changelog.sh 0.2.0-alpha
#
# Looks for a header matching `## [<version>]` (Keep a Changelog convention)
# and prints everything between that header and the next `## ` header
# (exclusive). Trailing whitespace is trimmed.
#
# Exits non-zero with a clear stderr message if the section can't be found.

set -euo pipefail

VERSION="${1:-}"
CHANGELOG="${2:-CHANGELOG.md}"

if [ -z "$VERSION" ]; then
    echo "ERROR: version is required" >&2
    echo "Usage: $0 <version> [path]" >&2
    exit 2
fi

if [ ! -f "$CHANGELOG" ]; then
    echo "ERROR: $CHANGELOG not found" >&2
    exit 2
fi

# awk: print lines between matching `## [VERSION]` (start) and the next
# `## ` header (end). Skip the header line itself; print everything in
# between. The /^## \[/ on a previously-matched section flips off.
awk -v v="$VERSION" '
    BEGIN { in_section = 0 }
    # Match the version header — supports `## [0.2.1]` and `## [0.2.1] — date`
    $0 ~ "^## \\[" v "\\]" { in_section = 1; next }
    # Any other `## [` header ends the current section
    /^## \[/ { in_section = 0 }
    in_section { print }
' "$CHANGELOG" | sed -e 's/[[:space:]]*$//' -e '/^$/N;/\n$/D'
