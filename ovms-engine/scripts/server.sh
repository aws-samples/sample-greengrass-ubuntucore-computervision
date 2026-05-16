#!/bin/bash -eu
# OVMS server startup wrapper
# Uses modelctl to determine the active engine and run its server script.
# The engine's server script starts OVMS with the appropriate device plugin.

engine="$(modelctl show-engine --format=json | jq -r .name)"
modelctl run "$SNAP/engines/$engine/server" --wait-for-components
