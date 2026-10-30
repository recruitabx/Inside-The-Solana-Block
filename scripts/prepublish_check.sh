#!/usr/bin/env bash
# Pre-publication checks. Exit code 0 only if every check passes.
#   1. no secrets in the working tree or in any commit of the history
#   2. no service/ops files ever committed
#   3. no em-dash characters in text files
#   4. relative links in Markdown files point to existing files
#   5. tests pass and `verify` runs from a fresh clone (optional: --clone)
set -u
cd "$(git rev-parse --show-toplevel)"
fail=0
ok(){ echo "PASS $1"; }
ko(){ echo "FAIL $1"; fail=1; }

SECRET_RE='(api[-_]?key=[A-Za-z0-9-]{8,}|Bearer [A-Za-z0-9._-]{20,}|BEGIN [A-Z ]*PRIVATE KEY|\[([0-9]{1,3}, ?){63}[0-9]{1,3}\]|Claude""-Session|claude\.ai/code/session|ghp_[A-Za-z0-9]{20,}|xox[bp]-[A-Za-z0-9-]{10,})'

# 1a working tree (tracked files)
if git ls-files -z | xargs -0 grep -IlE "$SECRET_RE" 2>/dev/null | grep -q .; then
  ko "secret-like strings in tracked files:"; git ls-files -z | xargs -0 grep -IlE "$SECRET_RE"
else ok "no secret-like strings in tracked files"; fi
# 1b full history (all blobs ever committed + commit messages)
hist=$(git rev-list --all | while read c; do git grep -IlE "$SECRET_RE" "$c" -- 2>/dev/null; done | sort -u)
msgs=$(git log --all --format=%B | grep -cE "$SECRET_RE")
if [ -n "$hist" ] || [ "$msgs" != "0" ]; then ko "secret-like strings in history: files=[$hist] messages=$msgs"; else ok "no secret-like strings in history (files and messages)"; fi

# 2 service files ever committed
SVC_RE='(^|/)(ops/|PLAN\.md|DECISIONS\.md|STATUS\.md|STATE|PUSH\.md|SUBMISSION\.md|KICKOFF|gates/|competitive\.md|agents\.log|wallet\.json|keypair\.json|\.env$|secrets/)'
svc=$(git log --all --name-only --format= | grep -E "$SVC_RE" | grep -v '\.env\.example$' | sort -u)
if [ -n "$svc" ]; then ko "service/secret files in history: $svc"; else ok "no service or key files in history"; fi

# 3 em-dash
em=$(git ls-files -z | xargs -0 grep -Il $'\xe2\x80\x94' 2>/dev/null)
if [ -n "$em" ]; then ko "em-dash found in: $em"; else ok "no em-dash characters"; fi

# 4 relative markdown links
bad=0
while IFS= read -r f; do
  d=$(dirname "$f")
  for l in $(grep -oE '\]\([^)#[:space:]]+' "$f" | sed 's/](//' | grep -vE '^(https?:|mailto:)'); do
    [ -e "$d/$l" ] || { echo "  broken link in $f -> $l"; bad=1; }
  done
done < <(git ls-files '*.md')
[ $bad = 0 ] && ok "relative Markdown links resolve" || ko "broken relative Markdown links"

# 5 optional fresh-clone check
if [ "${1:-}" = "--clone" ]; then
  tmp=$(mktemp -d); git clone -q . "$tmp/repo" && (cd "$tmp/repo" && docker compose run --rm test >/dev/null 2>&1) \
    && ok "tests pass in a fresh clone" || ko "tests fail in a fresh clone"
  rm -rf "$tmp"
fi
[ $fail = 0 ] && echo "PREPUBLISH: PASS" || echo "PREPUBLISH: FAIL"
exit $fail
