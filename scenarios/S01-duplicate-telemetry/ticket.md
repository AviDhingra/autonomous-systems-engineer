# S01 - Duplicate telemetry after retry

Operators report that a device/client may retry a telemetry request after a network timeout. When the same device sends the same logical `request_id` again, FleetOps must not create a second logical telemetry event.

Investigate the FleetOps source, find why a retry can create a duplicate, and propose the smallest safe application-code repair. Do not change tests or benchmark files.
