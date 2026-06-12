import os

TENANT_NAMESPACE = os.environ.get("TENANT_NAMESPACE", "calunga-tenant")
RELEASE_NAMESPACE = os.environ.get("RELEASE_NAMESPACE", "rhtap-releng-tenant")
APPLICATION = os.environ.get("APPLICATION", "calunga-v2-index-main")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "UGZCNQU69")

MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
STALL_TIMEOUT_MINUTES = int(os.environ.get("STALL_TIMEOUT_MINUTES", "30"))

# Label keys
LBL_PIPELINE_TYPE = "pipelines.appstudio.openshift.io/type"
LBL_APPLICATION = "appstudio.openshift.io/application"
LBL_COMPONENT = "appstudio.openshift.io/component"
LBL_SNAPSHOT = "appstudio.openshift.io/snapshot"
LBL_BUILD_PLR = "appstudio.openshift.io/build-pipelinerun"
LBL_RELEASE_NAME = "release.appstudio.openshift.io/name"
LBL_RELEASE_NS = "release.appstudio.openshift.io/namespace"

# Annotation keys shared across PAC resources
ANN_SHA = "pac.test.appstudio.openshift.io/sha"
ANN_SHA_TITLE = "pac.test.appstudio.openshift.io/sha-title"

# Also present as labels on all resources
LBL_SHA = "pac.test.appstudio.openshift.io/sha"
