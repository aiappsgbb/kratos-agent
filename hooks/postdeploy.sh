#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="skills"
STORAGE_ACCOUNT="${AZURE_BLOB_STORAGE_ACCOUNT_NAME:-}"
USE_CASES_DIR="use-cases"

if [ -z "$STORAGE_ACCOUNT" ]; then
  echo "⚠️  AZURE_BLOB_STORAGE_ACCOUNT_NAME is not set. Skipping skills upload."
  exit 0
fi

if [ ! -d "$USE_CASES_DIR" ]; then
  echo "⚠️  '$USE_CASES_DIR' directory not found. Skipping skills upload."
  exit 0
fi

# Discover available use-cases
USE_CASES=()
for dir in "$USE_CASES_DIR"/*/; do
  name="$(basename "$dir")"
  [ "$name" = "*" ] && continue
  USE_CASES+=("$name")
done

if [ ${#USE_CASES[@]} -eq 0 ]; then
  echo "⚠️  No use-cases found in '$USE_CASES_DIR'. Skipping skills upload."
  exit 0
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Upload Skills to Azure Blob Storage            ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Storage Account: $STORAGE_ACCOUNT"
echo "║  Container:       $CONTAINER_NAME"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Non-interactive mode: KRATOS_AUTO_UPLOAD_USE_CASES=1 uploads ALL use-cases
# without prompting. Required for CI / non-TTY runs.
if [[ "${KRATOS_AUTO_UPLOAD_USE_CASES:-0}" == "1" ]]; then
  echo "🤖 KRATOS_AUTO_UPLOAD_USE_CASES=1 set — uploading ALL use-cases non-interactively."
  SELECTION="A"
else
  echo "Available use-cases:"
  echo ""
  for i in "${!USE_CASES[@]}"; do
    echo "  $((i + 1)). ${USE_CASES[$i]}"
  done
  echo "  A. All use-cases"
  echo "  S. Skip (do not upload)"
  echo ""
  read -r -p "Select use-case(s) to upload (number, A for all, S to skip): " SELECTION
fi

if [[ "$SELECTION" =~ ^[Ss]$ ]]; then
  echo "Skipping skills upload."
  exit 0
fi

SELECTED=()
if [[ "$SELECTION" =~ ^[Aa]$ ]]; then
  SELECTED=("${USE_CASES[@]}")
else
  # Support comma-separated numbers like "1,3"
  IFS=',' read -ra NUMS <<< "$SELECTION"
  for num in "${NUMS[@]}"; do
    num="$(echo "$num" | tr -d ' ')"
    if [[ "$num" =~ ^[0-9]+$ ]] && [ "$num" -ge 1 ] && [ "$num" -le "${#USE_CASES[@]}" ]; then
      SELECTED+=("${USE_CASES[$((num - 1))]}")
    else
      echo "⚠️  Invalid selection: $num"
    fi
  done
fi

if [ ${#SELECTED[@]} -eq 0 ]; then
  echo "No valid use-cases selected. Skipping."
  exit 0
fi

for use_case in "${SELECTED[@]}"; do
  LOCAL_PATH="$USE_CASES_DIR/$use_case"
  echo ""
  echo "🔄 Uploading '$use_case' → blob://$CONTAINER_NAME/$use_case/ ..."

  # Delete existing blobs for this use-case first (replace, not merge), BUT
  # preserve eval run history under evals/runs/ — those are runtime artefacts
  # written by the backend, not source-controlled inputs we ship from the repo.
  # Without this guard, every postdeploy wipes the entire eval history and
  # the e2e-smoke `04-evals` spec fails until a fresh validation run is queued.
  echo "   Clearing existing blobs under 'use-cases/$use_case/' (preserving evals/runs/)..."
  EXISTING_BLOBS="$(az storage blob list \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER_NAME" \
    --prefix "use-cases/$use_case/" \
    --auth-mode login \
    --query "[?!contains(name, '/evals/runs/')].name" \
    --output tsv 2>/dev/null || true)"

  if [ -n "$EXISTING_BLOBS" ]; then
    echo "$EXISTING_BLOBS" | while IFS= read -r blob_name; do
      [ -z "$blob_name" ] && continue
      az storage blob delete \
        --account-name "$STORAGE_ACCOUNT" \
        --container-name "$CONTAINER_NAME" \
        --name "$blob_name" \
        --auth-mode login \
        --only-show-errors 2>/dev/null || true
    done
  fi

  # Upload all files from the local use-case folder
  az storage blob upload-batch \
    --account-name "$STORAGE_ACCOUNT" \
    --destination "$CONTAINER_NAME" \
    --source "$LOCAL_PATH" \
    --destination-path "use-cases/$use_case" \
    --auth-mode login \
    --overwrite \
    --only-show-errors

  echo "   ✅ '$use_case' uploaded successfully."
done

echo ""
echo "🎉 Skills upload complete."
