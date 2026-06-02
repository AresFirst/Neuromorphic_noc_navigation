#!/usr/bin/env bash
set -euo pipefail

find results -mindepth 1 -maxdepth 1 ! -name '.gitkeep' -exec rm -rf {} +
