import os

TENANT_NAMESPACE = os.environ.get("TENANT_NAMESPACE", "calunga-tenant")
RELEASE_NAMESPACE = os.environ.get("RELEASE_NAMESPACE", "rhtap-releng-tenant")
APPLICATION = os.environ.get("APPLICATION", "calunga-v2-index-main")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "")

MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
STALL_TIMEOUT_MINUTES = int(os.environ.get("STALL_TIMEOUT_MINUTES", "30"))

# AI failure analysis
AI_ANALYSIS_ENABLED = os.environ.get("AI_ANALYSIS_ENABLED", "false").lower() == "true"
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_REGION = os.environ.get("GOOGLE_CLOUD_REGION", "global")
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")
AI_MAX_LOG_LINES = int(os.environ.get("AI_MAX_LOG_LINES", "200"))
AI_TIMEOUT_SECONDS = int(os.environ.get("AI_TIMEOUT_SECONDS", "30"))

# Label keys
LBL_PIPELINE_TYPE = "pipelines.appstudio.openshift.io/type"
LBL_APPLICATION = "appstudio.openshift.io/application"
LBL_COMPONENT = "appstudio.openshift.io/component"
LBL_SNAPSHOT = "appstudio.openshift.io/snapshot"
LBL_BUILD_PLR = "appstudio.openshift.io/build-pipelinerun"
LBL_RELEASE_NAME = "release.appstudio.openshift.io/name"
LBL_RELEASE_NS = "release.appstudio.openshift.io/namespace"
LBL_EVENT_TYPE = "pac.test.appstudio.openshift.io/event-type"

# Annotation keys shared across PAC resources
ANN_SHA = "pac.test.appstudio.openshift.io/sha"
ANN_SHA_TITLE = "pac.test.appstudio.openshift.io/sha-title"

# Also present as labels on all resources
LBL_SHA = "pac.test.appstudio.openshift.io/sha"
