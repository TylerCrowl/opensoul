#!/usr/bin/env bash
# Fetch the public-domain / CC0 demo music candidates from Wikimedia Commons and verify hashes.
set -euo pipefail
cd "$(dirname "$0")/../assets/music_candidates"
UA="OpenSoul/0.1 (demo music fetch)"
fetch() { [ -f "$1" ] || curl -sfL -A "$UA" -o "$1" "$2"; echo "$3  $1" | sha256sum -c -; }
fetch long_trail_kevin_macleod.ogg "https://upload.wikimedia.org/wikipedia/commons/2/29/Kevin_MacLeod_-_Long_Trail.ogg" cf0f7ccf86a922e04ef37ccb33d8cf6418f2019e706d025ca54b1e32ae8b49d3
fetch skysand_monplaisir.ogg "https://upload.wikimedia.org/wikipedia/commons/2/22/Monplaisir_-_04_-_Skysand.ogg" 0fbce1c8e24aadf8026036819b1abe150a9c9903c687df8537e4d4d577123200
fetch no_need_to_monplaisir.ogg "https://upload.wikimedia.org/wikipedia/commons/7/7f/Monplaisir_-_01_-_No_need_to.ogg" 23c2218f84e9b639295deb1b652043c060e7626a5d927f9cfdaf79f60c34a4b5
