# Calunga Release Watcher

A Kubernetes controller that watches the CI/CD pipeline lifecycle in
[Konflux / AppStudio](https://konflux-ci.dev/) and sends Slack
notifications on failures and successful releases.

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
pipelines and enables notifications going forward. This avoids
re-notifying about old events after a restart.

## Project structure

```
src/calunga_release_watcher/
  config.py      — Environment-variable configuration and Kubernetes label/annotation constants
  handlers.py    — kopf event handlers (wiring between Kubernetes events and the tracker)
  tracker.py     — Core state machine: PipelineTracker, PipelineInfo, and helper functions
  slack.py       — Sends Slack notifications via the Slack Web API
```

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `TENANT_NAMESPACE` | `calunga-tenant` | Namespace where builds, tests, snapshots, and releases live |
| `RELEASE_NAMESPACE` | `rhtap-releng-tenant` | Namespace where release PipelineRuns run |
| `APPLICATION` | `calunga-v2-index-main` | AppStudio application name to filter resources by |
| `SLACK_BOT_TOKEN` | *(empty)* | Slack Bot token. If unset, Slack notifications are skipped |
| `SLACK_CHANNEL` | `UGZCNQU69` | Slack channel ID to post notifications to |
| `K8S_TOKEN` | *(empty)* | Kubernetes bearer token for remote cluster auth |
| `K8S_API_URL` | *(empty)* | Kubernetes API server URL. If unset, uses local kubeconfig |
