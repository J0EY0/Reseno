set -euo pipefail

snapshot=backend/app/services/model_metadata_snapshot.json
report="$RUNNER_TEMP/model-metadata-pr.md"
previous="$RUNNER_TEMP/model-metadata-previous.json"

if [ -z "$PREVIOUS_HEAD" ] || ! cmp -s "$snapshot" "$previous"; then
  if [ -n "$PREVIOUS_HEAD" ]; then
    other_files="$(git diff --name-only "HEAD...$PREVIOUS_HEAD" -- . ":!$snapshot")"
    manual_commits="$(git log --format='%ae %ce' "HEAD..$PREVIOUS_HEAD" | awk '$0 != "41898282+github-actions[bot]@users.noreply.github.com 41898282+github-actions[bot]@users.noreply.github.com"')"
    if [ -n "$other_files" ] || [ -n "$manual_commits" ]; then
      echo '::error::The update branch contains manual changes. Review and merge or close its PR before refreshing it.'
      exit 1
    fi
  fi
  git switch -c "$UPDATE_BRANCH"
  git config user.name 'github-actions[bot]'
  git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
  git add -- "$snapshot"
  git commit -m "chore(models): refresh bundled model metadata"
  git push --force-with-lease="refs/heads/$UPDATE_BRANCH:$PREVIOUS_HEAD" origin "HEAD:refs/heads/$UPDATE_BRANCH"
fi

cat >> "$report" <<'EOF'

Validation: model metadata, thinking-mode and context tests passed in the update workflow.
EOF
if [ -n "$EXISTING_PR" ]; then
  gh pr edit "$EXISTING_PR" --body-file "$report"
else
  gh pr create --base "$BASE_BRANCH" --head "$UPDATE_BRANCH" \
    --title "chore(models): refresh bundled model metadata" --body-file "$report"
fi
