#!/usr/bin/env bash
set -euo pipefail

awslocal s3api head-bucket --bucket research-artifacts >/dev/null 2>&1 || \
  awslocal s3api create-bucket --bucket research-artifacts >/dev/null
