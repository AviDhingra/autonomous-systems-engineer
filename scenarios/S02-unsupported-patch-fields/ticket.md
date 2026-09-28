# S02 - Firmware sync script silently ignores typo'd patch fields

The nightly firmware-sync batch job calls the device service directly
(bypassing the HTTP API) to push firmware updates in bulk. Operators found
that a recent sync run reported success for every device, but a handful of
devices never actually updated. The sync script had a typo in the field
name it was sending, and FleetOps applied the patch anyway without
updating anything and without reporting an error.

Investigate the FleetOps source, find why a patch with an unsupported
field name is accepted silently instead of being rejected, and propose the
smallest safe application-code repair. Do not change tests or benchmark
files.
