# Deploy Temporal with Podman Compose

This directory runs a local Temporal development stack using
[podman-compose.yml](podman-compose.yml). It includes Temporal Server, Web UI, PostgreSQL,
Elasticsearch, and initialization scripts. IBM MQ, the AI endpoint, and the enquiry application's
CLIENT and WORKER processes must be started separately.

The commands below use Bash on Linux and run from this directory unless stated otherwise.
Command blocks with `set -e` run in a subshell and stop if a command fails.
This is a development configuration: PostgreSQL uses the bundled `temporal` credentials,
Elasticsearch security is disabled, and Temporal/UI have no configured authentication or TLS.
Ports 7233 and 8080 are published on all host interfaces; keep access restricted to your
development environment.

## What the stack contains

| Compose service | Purpose | Host access |
| --- | --- | --- |
| `postgresql` | Temporal workflow state in PostgreSQL | `127.0.0.1:5432` |
| `elasticsearch` | Workflow visibility/search index | `http://127.0.0.1:9200` |
| `temporal-admin-tools` | One-shot PostgreSQL schema and Elasticsearch index setup | No published port |
| `temporal` | Temporal Server, using the `postgres12` persistence plugin | `localhost:7233` (gRPC) |
| `temporal-create-namespace` | Waits for the server and creates the `default` namespace | No published port |
| `temporal-ui` | Temporal Web UI | `http://localhost:8080` |

Containers communicate through the bridge network named `temporal-network`. PostgreSQL and
Elasticsearch data reside in the named volumes `temporal-postgres-data` and `temporal-es-data`;
their actual Podman names can include the Compose project prefix. Fixed container names and
the fixed network name mean multiple copies of this stack can collide on the same Podman host.

## 1. Prepare Podman and a Compose provider

Install [Podman](https://podman.io/docs/installation) and a Compose provider such as
`podman-compose` or Docker Compose. `podman compose` delegates to an external provider; installing
Podman alone does not guarantee Compose is available. See the
[Podman Compose documentation](https://docs.podman.io/en/latest/markdown/podman-compose.1.html).

On Linux, Podman runs directly without a Podman machine. Verify the installation and provider:

```bash
podman info
podman compose version
```

If both providers are installed, Podman normally prefers Docker Compose. To explicitly select
an installed `podman-compose` executable:

```bash
export PODMAN_COMPOSE_PROVIDER="$(command -v podman-compose)"
podman compose version
```

The provider must support `run --rm --no-deps`, service health conditions, and the Compose file's
bind mounts. Use `podman compose --help` to inspect its supported commands. Allow registry access
to `docker.io` for online downloads, or load the offline archives below. Allow sufficient host
memory/disk for all four long-running services and access to this
checkout for bind mounts. Keep `scripts/*.sh` as UTF-8 with LF line endings for Linux execution.

From the application repository root:

```bash
cd deployment/podman-compose
```

## 1a. Download or load container images

Before step 2, choose either an online download or an offline archive load. These five images
match the version settings shown in step 2; the two initialization services share admin-tools.
Run all deployment commands with the same Podman connection and user so Compose can find the
images in the same image store.

### Online: download from Docker Hub

On a host with internet access, run:

```bash
(
  set -e
  podman pull docker.io/library/postgres:16 || { printf '%s\n' 'PostgreSQL image download failed' >&2; exit 1; }
  podman pull docker.io/library/elasticsearch:7.17.27 || { printf '%s\n' 'Elasticsearch image download failed' >&2; exit 1; }
  podman pull docker.io/temporalio/admin-tools:1.31.0 || { printf '%s\n' 'Temporal admin-tools image download failed' >&2; exit 1; }
  podman pull docker.io/temporalio/server:1.31.0 || { printf '%s\n' 'Temporal Server image download failed' >&2; exit 1; }
  podman pull docker.io/temporalio/ui:2.49.1 || { printf '%s\n' 'Temporal UI image download failed' >&2; exit 1; }
)
```

### Offline: prepare and load `.tar` archives

For a hardened deployment host without internet access, prepare archives on a separate connected
host. Use a host with the same container OS/CPU architecture as the deployment host
(for example, Linux/amd64). Run the commands from this deployment directory. On native Linux,
use the same user for loading images and running Compose; rootless Podman and `sudo podman`
have separate image stores.

Run this block on the connected host to download and save all five images.
The subshell exits on a failed command.

```bash
(
  set -e
  mkdir -p ./images
  podman pull docker.io/library/postgres:16
  podman pull docker.io/library/elasticsearch:7.17.27
  podman pull docker.io/temporalio/admin-tools:1.31.0
  podman pull docker.io/temporalio/server:1.31.0
  podman pull docker.io/temporalio/ui:2.49.1
  podman save --format docker-archive --output ./images/postgres-16.tar docker.io/library/postgres:16
  podman save --format docker-archive --output ./images/elasticsearch-7.17.27.tar docker.io/library/elasticsearch:7.17.27
  podman save --format docker-archive --output ./images/temporal-admin-tools-1.31.0.tar docker.io/temporalio/admin-tools:1.31.0
  podman save --format docker-archive --output ./images/temporal-server-1.31.0.tar docker.io/temporalio/server:1.31.0
  podman save --format docker-archive --output ./images/temporal-ui-2.49.1.tar docker.io/temporalio/ui:2.49.1
  (cd ./images && sha256sum *.tar > SHA256SUMS)
)
```

Transfer the five archives and their SHA256 hashes using your environment's approved transfer
method. On the offline host, place the archives in an `images` directory under this deployment
directory. Transfer `images/SHA256SUMS` alongside the archives.
If matching archives are already supplied, start directly with this transfer/load procedure.

Verify the checksum manifest, then load the archives. Run this block from the deployment
directory; a checksum or load failure stops the remaining commands.

```bash
(
  set -e
  (cd ./images && sha256sum --check SHA256SUMS)
  podman load --input ./images/postgres-16.tar
  podman load --input ./images/elasticsearch-7.17.27.tar
  podman load --input ./images/temporal-admin-tools-1.31.0.tar
  podman load --input ./images/temporal-server-1.31.0.tar
  podman load --input ./images/temporal-ui-2.49.1.tar
  podman image inspect docker.io/library/postgres:16 docker.io/library/elasticsearch:7.17.27 docker.io/temporalio/admin-tools:1.31.0 docker.io/temporalio/server:1.31.0 docker.io/temporalio/ui:2.49.1
)
```

Use image archives created by [podman save](https://docs.podman.io/en/latest/markdown/podman-save.1.html)
and restored with [podman load](https://docs.podman.io/en/latest/markdown/podman-load.1.html).
Container filesystem exports are not a substitute for these image archives. Keep archives
outside version control.

After either route, verify all five exact image references are available locally:

```bash
(
  set -e
  podman image inspect docker.io/library/postgres:16 docker.io/library/elasticsearch:7.17.27 docker.io/temporalio/admin-tools:1.31.0 docker.io/temporalio/server:1.31.0 docker.io/temporalio/ui:2.49.1 || { printf '%s\n' 'Required image missing; complete download or load before continuing' >&2; exit 1; }
)
```

For offline deployment, skip `compose pull` in step 2. The Compose file does not request an
always-pull policy; retain the exact loaded tags in `.env` and remove any external pull-policy
override that forces registry access. If the provider supports it, use `--pull never` on later
`up` and `run` commands to explicitly prevent downloads; check each command's `--help` first.

## 2. Configure image versions

Create `.env` **in this directory** with the following contents. The file is ignored by Git.
These values match the [Temporal upstream Compose example](https://github.com/temporalio/samples-server/blob/main/compose/.env)
inspected on 2026-09-19; they are a starting point, not a locally verified compatibility matrix.

```dotenv
POSTGRESQL_VERSION=16
ELASTICSEARCH_VERSION=7.17.27
TEMPORAL_VERSION=1.31.0
TEMPORAL_ADMINTOOLS_VERSION=1.31.0
TEMPORAL_UI_VERSION=2.49.1
```

All five variables are required because this Compose file has no default image tags. Keep server
and admin-tools versions aligned. The scripts use the `postgres12` plugin and PostgreSQL v12
schema directory; `postgres12` is the plugin name, not a requirement to use PostgreSQL image 12.
The Elasticsearch configuration selects `ES_VERSION=v7`. Do not change database major versions
on existing volumes without a migration plan.

This deployment `.env` supplies Compose image interpolation. It is separate from the
application's root `.env`, which supplies `OFTL_*` settings. PostgreSQL credentials and service
configuration are literal values in the YAML; adding unrelated keys to this `.env` will not
override them. Existing shell variables can override `.env` values, so inspect the rendered file:

```bash
(
  set -e
  podman compose --env-file .env -f podman-compose.yml config || { printf '%s\n' 'Compose configuration failed' >&2; exit 1; }
)
```

If you changed image versions from step 1a, download or load those exact versions before
continuing. On an online host, you can download the configured images with the following
command; **skip this command on an offline host**:

```bash
(
  set -e
  podman compose --env-file .env -f podman-compose.yml pull || { printf '%s\n' 'Image download failed' >&2; exit 1; }
)
```

Check for fully resolved image tags and available host ports 5432, 9200, 7233, and 8080.
The application's example AI endpoint also uses host port 8080. If an AI server already uses
that port, change the UI mapping to an unused host port, for example `8081:8080`, and open
`http://localhost:8081` instead. The UI's internal container port remains 8080.

## 3. Start PostgreSQL and Elasticsearch

Use this sequence for a **fresh deployment**. Avoid an initial unqualified `up -d`: Temporal
depends on database health but does not wait for `temporal-admin-tools` to finish schema setup.

```bash
(
  set -e
  podman compose --env-file .env -f podman-compose.yml up -d postgresql elasticsearch || { printf '%s\n' 'Database startup failed' >&2; exit 1; }
  podman compose --env-file .env -f podman-compose.yml ps
  podman inspect --format '{{.State.Health.Status}}' temporal-postgresql temporal-elasticsearch
)
```

Wait until **both health statuses are `healthy`** before continuing. Repeat the last command to
check readiness. For startup errors:

```bash
podman compose --env-file .env -f podman-compose.yml logs --tail=100 postgresql elasticsearch
```

The PostgreSQL health check uses `pg_isready -U temporal`; Elasticsearch waits for yellow or
better cluster health. The Compose file gives each health check a 30-second start period and
up to 60 retries at five-second intervals.

## 4. Initialize schemas once

```bash
(
  set -e
  podman compose --env-file .env -f podman-compose.yml run --rm --no-deps temporal-admin-tools || { printf '%s\n' 'Schema initialization failed; do not start Temporal yet' >&2; exit 1; }
)
```

This runs [scripts/setup-postgres-es.sh](scripts/setup-postgres-es.sh), which creates the
`temporal` database, initializes and updates its schema, then creates the Elasticsearch
visibility index `temporal_visibility_v1_dev`. It uses `temporal-elasticsearch-tool` when present
at the path checked by the script, otherwise the bundled curl-based fallback.

Expect `PostgreSQL and Elasticsearch setup complete` and exit code 0. `--no-deps` uses the
already-running databases; `--rm` removes the temporary initialization container afterward.

The script unconditionally attempts database creation. It is not a safe general-purpose
restart or upgrade command: rerunning it on existing or partially initialized volumes can fail
with an existing-database error. Inspect the database/schema and the original error before
recovering a partial setup; do not delete persisted data simply to silence that error.

## 5. Start Temporal, initialize the namespace, and start the UI

```bash
(
  set -e
  podman compose --env-file .env -f podman-compose.yml up -d temporal || { printf '%s\n' 'Temporal startup failed' >&2; exit 1; }
  podman compose --env-file .env -f podman-compose.yml run --rm --no-deps temporal-create-namespace || { printf '%s\n' 'Namespace initialization failed; see troubleshooting below' >&2; exit 1; }
  podman compose --env-file .env -f podman-compose.yml up -d temporal-ui || { printf '%s\n' 'UI startup failed' >&2; exit 1; }
)
```

[scripts/create-namespace.sh](scripts/create-namespace.sh) waits for the TCP port, then Temporal
cluster health, then describes or creates namespace `default`. Expect `Namespace 'default'
created` or `Namespace 'default' already exists` and exit code 0. Its wait-loop defaults are
30 attempts with five seconds between attempts; individual commands can add additional time.

**Known script defect:** the failed namespace-create branch references `MAX_ATTdMPTS` instead
of `MAX_ATTEMPTS`. Under `set -u`, that branch exits before retrying. Successful creation or an
existing namespace bypasses the defect. If it occurs, check server health, then rerun this step
once the server is ready; see the manual namespace commands below for unsuppressed error output.

The guide uses foreground, disposable initialization jobs so their exit codes are visible.
They will not remain as running services, and `logs temporal-create-namespace` will not retain
the output of a removed `run --rm` container.

## 6. Verify the deployment

```bash
podman compose --env-file .env -f podman-compose.yml ps
podman compose --env-file .env -f podman-compose.yml run --rm --no-deps --entrypoint temporal temporal-create-namespace operator cluster health --address temporal:7233
podman compose --env-file .env -f podman-compose.yml run --rm --no-deps --entrypoint temporal temporal-create-namespace operator namespace describe --namespace default --address temporal:7233
```

The four long-running services should be running, cluster health should succeed, and namespace
description should return `default`. The server container's own health check only tests TCP
port 7233; the CLI health check above verifies more than an open port. Open
[Temporal Web UI](http://localhost:8080) and select `default`. An empty workflow list is expected
until an application submits a workflow.

For an optional submission smoke test:

```bash
(
  set -e
  podman compose --env-file .env -f podman-compose.yml run --rm --no-deps temporal-create-namespace /scripts/validate-temporal.sh || { printf '%s\n' 'Temporal submission smoke test failed' >&2; exit 1; }
)
```

[scripts/validate-temporal.sh](scripts/validate-temporal.sh) waits 15 seconds, checks health and
namespace access, then starts and terminates a synthetic `NonExistentWorkflow` on
`validation-queue`. It leaves a workflow history entry and tests server submission, not worker
execution or IBM MQ/AI integration. The printed `MAX_WAIT_TIME` setting is currently unused;
it does not implement a 300-second readiness loop.

## 7. Connect the enquiry application

For native CLIENT/WORKER processes on the host, set this in the **application-root** `.env`:

```dotenv
OFTL_AI_TEMPORALURL=localhost:7233
```

For application containers attached to `temporal-network`, use `temporal:7233` instead. A
container on a different network needs a reachable host endpoint; its own `localhost` does
not refer to the Temporal container. Configure MQ, AI, and prompts separately as described in
the [application README](../../README.md).

In separate terminals, from the application root:

```bash
uv run customer-enquiry-triage-worker
# Second terminal:
uv run customer-enquiry-triage-client
```

The application uses namespace `default` and task queue `CUSTOMER.ENQUIRY.REQUEST`. The current
application does not expose namespace, TLS, or API-key configuration. Use the explicit installed
commands above because the generic native CLI has a known mode-selection issue.

## Stop, resume, and retain data

Stop containers while keeping them and their volumes:

```bash
podman compose --env-file .env -f podman-compose.yml stop
```

Resume an initialized deployment without rerunning schema setup:

```bash
podman compose --env-file .env -f podman-compose.yml up -d postgresql elasticsearch
# Wait for both databases to become healthy, as in step 3.
podman compose --env-file .env -f podman-compose.yml up -d temporal temporal-ui
```

To remove the stack's containers and Compose-managed network while retaining named volumes:

```bash
podman compose --env-file .env -f podman-compose.yml down
```

Use the same directory, Compose project identity, and image versions when resuming. Do not
rerun schema initialization for an already initialized deployment. `down --volumes` is a
destructive reset: it removes the stack's persisted workflow state and visibility data. Use it
only when deliberately discarding this development deployment, then repeat the fresh setup.
These initialization scripts are not a database backup or rolling-upgrade procedure.

## Troubleshooting

| Symptom | Check or action |
| --- | --- |
| Compose provider not found | Install/configure a provider; verify `podman compose version` and `PODMAN_COMPOSE_PROVIDER`. |
| Cannot connect to Podman | Run `podman info`; check the Linux installation, user permissions, and any configured remote connection. |
| Missing variable or invalid image reference | Confirm all five image-version keys are in this directory's `.env`; inspect `config` output and shell overrides. |
| Image pull fails | Check registry access, proxy/DNS settings, selected tags, and architecture availability. |
| Port already allocated | Check the port mappings above, especially UI port 8080 versus the AI endpoint. Change the host-side mapping and matching client URL. |
| Database never becomes healthy | Read database logs; check host memory/disk and Elasticsearch bootstrap errors before retrying. |
| Missing schema/table errors in Temporal logs | Confirm step 4 completed successfully before starting the server. A healthy PostgreSQL socket does not prove schemas exist. |
| Database already exists during setup | Existing or partial initialization is present. Inspect its schema state; use the resume procedure for an initialized stack. |
| `MAX_ATTdMPTS: parameter not set` | Known typo in `create-namespace.sh`; check cluster health and use the manual commands below to see the actual namespace error. |
| `/scripts/*.sh` missing, permission errors, or unexpected shell tokens | Check host directory permissions for bind mounts, LF line endings, and SELinux labels. |
| Web UI opens but cannot connect | Check server health and UI logs; the UI backend connects to `temporal:7233` over `temporal-network`. |

Useful server/UI logs:

```bash
podman compose --env-file .env -f podman-compose.yml logs --tail=100 temporal temporal-ui
```

To diagnose namespace creation, first run the health and namespace-description commands in
step 6. Only if the server is healthy and `default` is absent, create it manually:

```bash
podman compose --env-file .env -f podman-compose.yml run --rm --no-deps --entrypoint temporal temporal-create-namespace operator namespace create --namespace default --address temporal:7233
```

On SELinux hosts, the two initialization services mount the same `scripts` directory using
different labels: schema setup uses shared `:z`, while namespace setup uses private `:Z`.
Concurrent access or later reuse can encounter relabeling problems. If affected, align both
shared script mounts to `:z,ro` in the Compose file. Podman's
[volume-label documentation](https://docs.podman.io/en/latest/markdown/podman-run.1.html)
explains the shared/private distinction. The staged commands above avoid concurrent setup jobs.

## Files and configuration actually used

| Path | Role in this deployment |
| --- | --- |
| [podman-compose.yml](podman-compose.yml) | Active six-service configuration. |
| [scripts/setup-postgres-es.sh](scripts/setup-postgres-es.sh) | Active PostgreSQL/Elasticsearch initializer. |
| [scripts/create-namespace.sh](scripts/create-namespace.sh) | Active namespace initializer. |
| [scripts/validate-temporal.sh](scripts/validate-temporal.sh) | Optional manual submission check; not invoked automatically. |
| [dynamicconfig/development-sql.yaml](dynamicconfig/development-sql.yaml) | Selected server dynamic configuration; sets `limit.maxIDLength=255` and enables development search-attribute cache refresh. |
| Other `scripts/setup-*.sh` files | Alternative Cassandra, MySQL, PostgreSQL-only, TLS, and OpenSearch examples; not selected by this Compose file. |
| `dynamicconfig/development-cass.yaml`, `dynamicconfig/docker.yaml` | Not selected by the current `DYNAMIC_CONFIG_FILE_PATH`. |

The dynamic configuration directory is mounted at `/etc/temporal/config/dynamicconfig` and the
server selects `config/dynamicconfig/development-sql.yaml`. The neighboring dynamic-config
README mentions `docker.yaml`, but that is not the file selected by this stack. Changing only
an unused file or adding variables for another backend will not switch the active deployment.

## Validation status

Reviewed against the checked-in Compose file and scripts on 2026-09-19. Podman and its Compose
provider were unavailable in the documentation environment, so image pulls, rendered Podman
Compose configuration, container startup, and the smoke test were not executed. Run the checks
above on the deployment host before treating the stack as verified. This documentation update
does not modify the Compose file or repair the known namespace-script typo.
