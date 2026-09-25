#!/usr/bin/env bash
#
# Verify the subscription-level prerequisites this template needs, BEFORE
# `azd provision` creates anything.
#
# Why this exists
# ---------------
# The Container Apps environment is injected into a custom VNet
# (infra/modules/container-apps-env.bicep sets infrastructureSubnetId with
# internal: false), so the platform allocates a public IP for it. On a
# subscription where the `Microsoft.Network/AllowBringYourOwnPublicIpAddress`
# feature is not registered, that allocation is refused and the environment
# fails to configure.
#
# Three things made that failure expensive to diagnose:
#
#   1. azd surfaces it as "A resource with this name already exists or is in a
#      conflicting state", which points nowhere near the real cause. The actual
#      message (`SubscriptionNotRegisteredForFeature`) is buried in the ARM
#      deployment details.
#   2. It happens *after* ~15 minutes of successful provisioning.
#   3. It leaves the Container Apps environment half-created. Bicep then reports
#      it as `Succeeded` on the next run without reconfiguring it, so every
#      retry fails on unrelated-looking Container App errors until the
#      environment is deleted by hand.
#
# Checking up front costs a few seconds and turns all of that into one clear
# message with nothing to clean up.
#
# This is not Windows- or macOS-specific: the feature is a property of the
# subscription, so an unprepared subscription fails identically on every OS.
#
# Escape hatches:
#   KRATOS_SKIP_PREREQ_CHECK=1   skip entirely (CI, or you know better)
#   KRATOS_PREREQ_TIMEOUT_MIN=N  how long to wait for registration (default 15)

set -uo pipefail

[ "${KRATOS_SKIP_PREREQ_CHECK:-0}" = "1" ] && exit 0

FEATURE_NAMESPACE="Microsoft.Network"
FEATURE_NAME="AllowBringYourOwnPublicIpAddress"
# Microsoft.ContainerService backs the cluster underneath a Container Apps
# environment. It is not auto-registered when the environment joins a custom
# VNet, and its absence produces an equally opaque failure.
REQUIRED_PROVIDERS="Microsoft.App Microsoft.ContainerService"
TIMEOUT_MIN="${KRATOS_PREREQ_TIMEOUT_MIN:-15}"
POLL_SECONDS=20

if ! command -v az >/dev/null 2>&1; then
  echo "⚠️  Azure CLI (az) not found — skipping the subscription prerequisite check."
  echo "    If provisioning fails on the Container Apps environment, see:"
  echo "    https://learn.microsoft.com/azure/container-apps/networking"
  exit 0
fi

# azd puts the target subscription in the environment; fall back to whatever the
# CLI has selected so the script is still useful when run by hand.
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-}"
if [ -z "$SUBSCRIPTION" ]; then
  SUBSCRIPTION="$(az account show --query id -o tsv 2>/dev/null || true)"
fi
if [ -z "$SUBSCRIPTION" ]; then
  echo "⚠️  No Azure subscription available yet — skipping the prerequisite check."
  echo "    Run 'az login' if provisioning then fails."
  exit 0
fi

AZ_SUB_ARGS=(--subscription "$SUBSCRIPTION")

echo "Checking Azure subscription prerequisites..."

# ── Resource providers ────────────────────────────────────────────────────────
PENDING_PROVIDERS=()
for provider in $REQUIRED_PROVIDERS; do
  state="$(az provider show --namespace "$provider" "${AZ_SUB_ARGS[@]}" \
    --query registrationState -o tsv 2>/dev/null || true)"
  if [ "$state" = "Registered" ]; then
    echo "  ✅ $provider"
    continue
  fi
  echo "  🔄 $provider is '${state:-unknown}' — registering..."
  if az provider register --namespace "$provider" "${AZ_SUB_ARGS[@]}" --only-show-errors >/dev/null 2>&1; then
    PENDING_PROVIDERS+=("$provider")
  else
    echo "  ⚠️  Could not register $provider. You may lack permission on this"
    echo "      subscription (Contributor or Owner is required)."
  fi
done

# ── Feature flag ──────────────────────────────────────────────────────────────
feature_state() {
  az feature show --namespace "$FEATURE_NAMESPACE" --name "$FEATURE_NAME" \
    "${AZ_SUB_ARGS[@]}" --query properties.state -o tsv 2>/dev/null || true
}

STATE="$(feature_state)"
if [ "$STATE" = "Registered" ]; then
  echo "  ✅ $FEATURE_NAMESPACE/$FEATURE_NAME"
else
  echo "  🔄 $FEATURE_NAMESPACE/$FEATURE_NAME is '${STATE:-NotRegistered}' — registering..."
  echo "     This is a one-time, subscription-wide operation. It is needed because"
  echo "     the Container Apps environment joins your VNet and needs a public IP."

  REGISTER_ERR="$(az feature register --namespace "$FEATURE_NAMESPACE" --name "$FEATURE_NAME" \
    "${AZ_SUB_ARGS[@]}" --only-show-errors 2>&1 >/dev/null)" || true

  if printf '%s' "$REGISTER_ERR" | grep -qiE "AuthorizationFailed|does not have authorization|Forbidden"; then
    echo ""
    echo "❌ You do not have permission to register features on this subscription."
    echo "   Registering needs Contributor or Owner. Ask an administrator to run:"
    echo ""
    echo "     az feature register --namespace $FEATURE_NAMESPACE --name $FEATURE_NAME --subscription $SUBSCRIPTION"
    echo "     az provider register --namespace $FEATURE_NAMESPACE --subscription $SUBSCRIPTION"
    echo ""
    echo "   Nothing has been provisioned — your subscription is untouched."
    exit 1
  fi

  DEADLINE=$(( $(date +%s) + TIMEOUT_MIN * 60 ))
  START=$(date +%s)
  while :; do
    STATE="$(feature_state)"
    [ "$STATE" = "Registered" ] && break
    NOW=$(date +%s)
    if [ "$NOW" -ge "$DEADLINE" ]; then
      echo ""
      echo "❌ $FEATURE_NAME is still '${STATE:-NotRegistered}' after ${TIMEOUT_MIN}m."
      echo "   Azure has accepted the request — registration is a global operation"
      echo "   and occasionally takes much longer."
      echo ""
      echo "   Nothing has been provisioned, so there is nothing to clean up."
      echo "   Re-run 'azd up' once this prints 'Registered':"
      echo ""
      echo "     az feature show --namespace $FEATURE_NAMESPACE --name $FEATURE_NAME \\"
      echo "       --query properties.state -o tsv"
      echo ""
      echo "   To wait longer instead:  KRATOS_PREREQ_TIMEOUT_MIN=45 azd up"
      echo "   To skip this check:      KRATOS_SKIP_PREREQ_CHECK=1 azd up"
      exit 1
    fi
    printf '     waiting (%dm%02ds / %dm)...\r' $(( (NOW - START) / 60 )) $(( (NOW - START) % 60 )) "$TIMEOUT_MIN"
    sleep "$POLL_SECONDS"
  done
  echo "     ✅ registered.                    "

  # A freshly registered feature only takes effect once its resource provider is
  # re-registered — without this the deployment still fails as if nothing changed.
  echo "  🔄 Propagating to $FEATURE_NAMESPACE..."
  az provider register --namespace "$FEATURE_NAMESPACE" "${AZ_SUB_ARGS[@]}" --only-show-errors >/dev/null 2>&1 || true
fi

# Providers registered above are asynchronous too, but they settle in seconds and
# ARM tolerates a deployment racing them, so report rather than block.
for provider in "${PENDING_PROVIDERS[@]:-}"; do
  [ -z "$provider" ] && continue
  state="$(az provider show --namespace "$provider" "${AZ_SUB_ARGS[@]}" \
    --query registrationState -o tsv 2>/dev/null || true)"
  [ "$state" = "Registered" ] || echo "  ℹ️  $provider is '${state}' — it should finish during provisioning."
done

echo "Prerequisites OK — starting provisioning."
exit 0
