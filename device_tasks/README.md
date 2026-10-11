# device_tasks

Shell scripts queued here run on the tablet, inside the repo folder, when
`scripts/device_agent.sh` is running in Termux. Each file is named
`<UTC timestamp>_<name>.sh` and runs once. The output comes back as
`<same name>.txt` on the `device-reports` branch.

Anything committed here runs on your device, so keep the repository private.
Every script that has ever run is in this folder's git history.
