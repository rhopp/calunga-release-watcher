# Calunga Release Watcher

A Kubernetes controller that watches the CI/CD pipeline lifecycle in
[Konflux / AppStudio](https://konflux-ci.dev/) and sends Slack
notifications on failures and successful releases.

When a pipeline fails, the controller can optionally run AI-powered
failure analysis using Claude Sonnet via Google Vertex AI to classify
the failure and suggest next steps.

The controller is **read-only** — it never creates or modifies Kubernetes
resources. It only reacts to changes.

## Pipeline lifecycle

Every code push triggers a pipeline that moves through these stages:

```
BUILD_RUNNING ─► BUILD_SUCCEEDED ─► SNAPSHOT_CREATED ─► TESTING ─► TESTS_PASSED ─► RELEASING ─► RELEASED
      │                                                    │                           │
      ▼                                                    ▼                           ▼
 BUILD_FAILED                                         TESTS_FAILED              RELEASE_FAILED
```

Once a pipeline reaches a terminal state (`RELEASED` or any `*_FAILED`
state), further updates for that commit SHA are ignored.

## How it works

The controller uses [kopf](https://kopf.readthedocs.io/) to watch four
types of Kubernetes resources, all filtered by application label:

| Resource | Namespace | What it represents |
|---|---|---|
| `PipelineRun` (type=build) | tenant | The build step |
| `Snapshot` | tenant | A snapshot of the built artifact |
| `PipelineRun` (type=test) | tenant | Integration test runs |
| `Release` | tenant | The release request |
| `PipelineRun` (type=managed) | release | The release pipeline that does the actual work |

Each Kubernetes event is routed to the `PipelineTracker`, which maintains
an in-memory map of commit SHA to pipeline state. State transitions
trigger log messages and, for terminal states, Slack notifications.

### Startup behavior

On startup kopf "resumes" all existing resources. The tracker absorbs
these silently during a 15-second grace period (`SYNC_GRACE_PERIOD`),
then calls `set_live()` which prunes already-finished and stale
pipelines and enables notifications going forward. SHAs seen during
the initial sync are remembered so that late watch re-deliveries of
old resources cannot create spurious notifications.

`SLACK_BOT_TOKEN` and `SLACK_CHANNEL` are validated at startup — the
pod will crash if either is missing.

### AI failure analysis

When `AI_ANALYSIS_ENABLED` is `true` and a pipeline fails, the analyzer:

1. Gathers context from the Kubernetes cluster (TaskRun conditions and
   pod logs from failed containers)
2. For test failures (detected via Snapshot), looks up all test
   PipelineRuns and aggregates results across all failed tests
3. Sends the context to Claude Sonnet via Google Vertex AI
4. Enriches the Slack notification with:
   - **Classification**: `fluke` (transient), `real` (genuine issue),
     `infra` (infrastructure), or `unknown`
   - **Confidence**: high, medium, or low
   - **Root cause**: 1-2 sentence explanation
   - **Suggestion**: actionable recommendation

AI analysis failures are non-blocking — the basic Slack notification
is always sent even if AI analysis fails.

## Project structure

```
src/calunga_release_watcher/
  config.py      — Environment-variable configuration and Kubernetes label/annotation constants
  handlers.py    — kopf event handlers (wiring between Kubernetes events and the tracker)
  tracker.py     — Core state machine: PipelineTracker, PipelineInfo, and helper functions
  slack.py       — Sends Slack notifications via the Slack Web API
  analyzer.py    — AI-powered failure analysis via Claude on Vertex AI
```

## Configuration

All configuration is via environment variables.

### Core

| Variable | Default | Description |
|---|---|---|
| `TENANT_NAMESPACE` | `calunga-tenant` | Namespace where builds, tests, snapshots, and releases live |
| `RELEASE_NAMESPACE` | `rhtap-releng-tenant` | Namespace where release PipelineRuns run |
| `APPLICATION` | `calunga-v2-index-main` | AppStudio application name to filter resources by |
| `SLACK_BOT_TOKEN` | *(empty)* | **Required.** Slack Bot token. Pod fails on startup if not set |
| `SLACK_CHANNEL` | *(empty)* | **Required.** Slack channel ID. Pod fails on startup if not set |
| `K8S_TOKEN` | *(empty)* | Kubernetes bearer token for remote cluster auth |
| `K8S_API_URL` | *(empty)* | Kubernetes API server URL. If unset, uses in-cluster config |
| `MAX_RETRIES` | `3` | Maximum retries for pipeline operations |
| `STALL_TIMEOUT_MINUTES` | `30` | Minutes before a stalled pipeline is considered failed |

### AI failure analysis

| Variable | Default | Description |
|---|---|---|
| `AI_ANALYSIS_ENABLED` | `false` | Set to `true` to enable AI failure analysis |
| `GOOGLE_CLOUD_PROJECT` | *(empty)* | GCP project ID for Vertex AI. Required when AI is enabled |
| `GOOGLE_CLOUD_REGION` | `global` | GCP region for Vertex AI |
| `AI_MODEL` | `claude-sonnet-4-6` | Anthropic model to use |
| `AI_MAX_LOG_LINES` | `200` | Maximum log lines to fetch per container |
| `AI_TIMEOUT_SECONDS` | `30` | Timeout for AI API calls |
| `GOOGLE_APPLICATION_CREDENTIALS` | *(unset)* | Path to GCP service account key file for Vertex AI auth |
