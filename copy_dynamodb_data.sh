#!/usr/bin/env bash

# This script saves the current state of dynamodb tables to be used as seed data in 
# the local dynamodb tables used for local/offline development

# CLI Help
[ "$1" = "-h" -o "$1" = "--help" ] && echo "
  This script saves the current state of dynamodb tables to be used as seed data in 
  the local dynamodb tables used for local/offline development

  Usage: 
    `basename $0` [-h]              Show this message
    `basename $0` <stage-name>      Provide the stage specifying which tables to copy
    `basename $0`                   Default uses 'dev' stage if no inputs provided.
" && return

# Define the directory to save the seed data
SEED_DIR="$( dirname -- "$0";)/sample_data/"

STAGE=${1:-prod}
echo "Using stage $STAGE"
STATUS_TABLE="photonranch-status-$STAGE"
PHASE_STATUS_TABLE="phase-status-$STAGE"

echo "Copying $STATUS_TABLE"
aws dynamodb scan --table-name $STATUS_TABLE        | jq .Items > "$SEED_DIR/statusTable.json"

echo "Copying $PHASE_STATUS_TABLE"
aws dynamodb scan --table-name $PHASE_STATUS_TABLE  | jq .Items > "$SEED_DIR/phaseStatusTable.json"