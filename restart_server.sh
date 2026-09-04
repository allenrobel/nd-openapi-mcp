#!/bin/bash
# Restart the nd-openapi-mcp LaunchDaemon on mm1e.
#
# The daemon is registered in the *system* domain (/Library/LaunchDaemons/com.nd-openapi-mcp.plist),
# so it must be addressed as system/<label>, not gui/<uid>/<label> — the gui form reports
# "Could not find service" and restarts nothing.
#
# kickstart -k restarts the running job but does NOT re-read a changed plist. After editing the plist
# (e.g. adding ND_DEFAULT_VERSION), reload it instead:
#   sudo launchctl bootout system/com.nd-openapi-mcp
#   sudo launchctl bootstrap system /Library/LaunchDaemons/com.nd-openapi-mcp.plist
set -euo pipefail
sudo launchctl kickstart -k system/com.nd-openapi-mcp
