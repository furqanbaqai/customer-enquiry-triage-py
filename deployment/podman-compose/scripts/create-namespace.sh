#!/bin/sh
set -eu

# ============================================================
# Configuration
# ============================================================

NAMESPACE=${DEFAULT_NAMESPACE:-default}
TEMPORAL_ADDRESS=${TEMPORAL_ADDRESS:-temporal:7233}
MAX_ATTEMPTS=${TEMPORAL_HEALTH_CHECK_MAX_ATTEMPTS:-30}
SLEEP_SECONDS=${TEMPORAL_HEALTH_CHECK_SLEEP_SECONDS:-5}

SERVER_HOST=$(echo "$TEMPORAL_ADDRESS" | cut -d: -f1)
SERVER_PORT=$(echo "$TEMPORAL_ADDRESS" | cut -d: -f2)

echo "Temporal namespace initialization"
echo "Namespace       : $NAMESPACE"
echo "Temporal address: $TEMPORAL_ADDRESS"
echo "Maximum attempts: $MAX_ATTEMPTS"
echo "Retry interval  : ${SLEEP_SECONDS}s"
echo


# ============================================================
# 1. Wait for Temporal TCP port
# ============================================================

echo "Waiting for Temporal server port to be available..."

attempt=1

while ! nc -z -w 10 "$SERVER_HOST" "$SERVER_PORT"; do

  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "ERROR: Temporal server port did not become available after $MAX_ATTEMPTS attempts"
    exit 1
  fi

  echo "Temporal server port not ready yet, waiting... (attempt $attempt/$MAX_ATTEMPTS)"

  attempt=$((attempt + 1))
  sleep "$SLEEP_SECONDS"

done

echo "Temporal server port is available."
echo


# ============================================================
# 2. Resolve Temporal container hostname
#
# Workaround for Temporal CLI / container DNS situations where
# TCP connectivity to temporal:7233 succeeds but the Temporal
# CLI returns:
#
#     context deadline exceeded
#
# The Temporal CLI therefore connects using the resolved
# container IP address.
# ============================================================

echo "Resolving Temporal server hostname '$SERVER_HOST'..."

RESOLVED_IP=$(
  getent hosts "$SERVER_HOST" 2>/dev/null |
    awk 'NR == 1 { print $1 }'
)

if [ -n "${RESOLVED_IP:-}" ]; then

  TEMPORAL_CLI_ADDRESS="${RESOLVED_IP}:${SERVER_PORT}"

  echo "Temporal hostname resolved:"
  echo "  $SERVER_HOST -> $RESOLVED_IP"
  echo "Temporal CLI address: $TEMPORAL_CLI_ADDRESS"

else

  echo "WARNING: Could not resolve '$SERVER_HOST' using getent."
  echo "Falling back to configured address: $TEMPORAL_ADDRESS"

  TEMPORAL_CLI_ADDRESS="$TEMPORAL_ADDRESS"

fi

echo


# ============================================================
# 3. Wait for Temporal API / gRPC health
# ============================================================

echo "Waiting for Temporal server to be healthy..."

attempt=1

while :; do

  if temporal operator cluster health \
      --address "$TEMPORAL_CLI_ADDRESS"; then

    echo "Temporal server is healthy."
    break

  fi

  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then

    echo "ERROR: Temporal server did not become healthy after $MAX_ATTEMPTS attempts"
    echo "Temporal CLI address used: $TEMPORAL_CLI_ADDRESS"

    exit 1

  fi

  echo "Temporal server not ready yet, waiting... (attempt $attempt/$MAX_ATTEMPTS)"

  attempt=$((attempt + 1))
  sleep "$SLEEP_SECONDS"

done

echo


# ============================================================
# 4. Check whether namespace already exists
# ============================================================

echo "Checking Temporal namespace '$NAMESPACE'..."

attempt=1

while :; do

  if temporal operator namespace describe \
      -n "$NAMESPACE" \
      --address "$TEMPORAL_CLI_ADDRESS" \
      >/dev/null 2>&1; then

    echo "Namespace '$NAMESPACE' already exists."
    break

  fi


  # ==========================================================
  # 5. Create namespace
  # ==========================================================

  echo "Namespace '$NAMESPACE' does not exist. Attempting creation..."

  if temporal operator namespace create \
      -n "$NAMESPACE" \
      --address "$TEMPORAL_CLI_ADDRESS" \
      >/dev/null 2>&1; then

    echo "Namespace '$NAMESPACE' created successfully."
    break

  fi


  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then

    echo "ERROR: Failed to create namespace '$NAMESPACE' after $MAX_ATTEMPTS attempts"
    echo "Temporal CLI address used: $TEMPORAL_CLI_ADDRESS"

    exit 1

  fi

  echo "Namespace operation not ready yet, waiting... (attempt $attempt/$MAX_ATTEMPTS)"

  attempt=$((attempt + 1))
  sleep "$SLEEP_SECONDS"

done


# ============================================================
# Completed
# ============================================================

echo
echo "Temporal namespace initialization completed successfully."