#!/bin/bash

set -ex

dir=$(dirname "${BASH_SOURCE[0]}")
source "${dir}/check_service_status.sh"

# Make sure that cron is running in the scripts container
check_service_status /etc/service/cron
exit 0