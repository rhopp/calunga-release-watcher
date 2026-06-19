# E2E Test Fixtures

Real Kubernetes resource bodies captured from the calunga-tenant namespace
via kubearchive. Used to test the AI failure analysis pipeline against
realistic data with mocked k8s API calls and real Vertex AI.

## Fixture structure

Each fixture is a JSON file containing the full context chain:

```json
{
  "_description": "Human-readable description of the failure scenario",
  "_expected_classification": ["fluke", "infra"],
  "body": { ... },           // The Snapshot or PipelineRun body
  "test_pipelineruns": [],    // Test PLRs returned by list_namespaced_custom_object
  "taskruns": {},             // TaskRun bodies keyed by name (for get_namespaced_custom_object)
  "pods": {},                 // Pod container info keyed by pod name (for read_namespaced_pod)
  "pod_logs": {}              // Logs keyed by pod name -> container name -> log text
}
```

The e2e test framework mocks `CustomObjectsApi`, `CoreV1Api`, and
`get_k8s_client` to serve this canned data, so `_build_context` runs
the full context assembly chain before sending to real Vertex AI.

## How to capture new fixtures

1. Set up kubearchive access:
   ```bash
   export KUBECONFIG=/path/to/kubeconfig
   KA_HOST="kubearchive-api-server-product-kubearchive.apps.kflux-prd-rh03.nnv1.p1.openshiftapps.com"
   TOKEN=$(kubectl config view --raw -o jsonpath='{.users[0].user.token}')
   ```

2. Find a failed Snapshot or PipelineRun (label selectors work):
   ```bash
   curl -sk "https://${KA_HOST}/apis/tekton.dev/v1/namespaces/calunga-tenant/pipelineruns?labelSelector=appstudio.openshift.io/snapshot=SNAP_NAME,pipelines.appstudio.openshift.io/type=test" \
     -H "Authorization: Bearer ${TOKEN}"
   ```

3. For each failed test PLR, get its TaskRuns:
   ```bash
   curl -sk "https://${KA_HOST}/apis/tekton.dev/v1/namespaces/calunga-tenant/taskruns?labelSelector=tekton.dev/pipelineRun=PLR_NAME" \
     -H "Authorization: Bearer ${TOKEN}"
   ```

4. Get pod info and logs:
   ```bash
   curl -sk "https://${KA_HOST}/api/v1/namespaces/calunga-tenant/pods/POD_NAME" \
     -H "Authorization: Bearer ${TOKEN}"
   curl -sk "https://${KA_HOST}/api/v1/namespaces/calunga-tenant/pods/POD_NAME/log?container=CONTAINER&tailLines=50" \
     -H "Authorization: Bearer ${TOKEN}"
   ```

5. Assemble into the fixture structure above, slimming to essential fields.

## Current fixtures

| File | Kind | Failure type | Expected classification |
|------|------|-------------|------------------------|
| `build_failure.json` | PipelineRun | Dependency resolution error (missing PyPI package) | real |
| `test_enterprise_contract_failure.json` | Snapshot | EC policy violations (untrusted tasks) | real, infra |
| `test_multi_wheel_check_failure.json` | Snapshot | Image pull back-off on 3 distros | fluke, infra |
