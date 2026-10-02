# Contributing

Contributions should be reproducible and should not include proprietary vendor
files, personal device inventories, IDA databases, or machine-specific logs.

Before opening a pull request:

1. Run: python -m compileall scripts
2. Run: python -m pytest when the optional test dependency is installed.
3. Run the firmware builder against a locally obtained official image and
   confirm that it rejects an image with a wrong hash.
4. Describe hardware, firmware revision, host OS, and measurement method for
   any new result.

Do not submit a firmware dump or a flasher result containing a user's device
instance path. Hashes, offsets, and anonymized measurements are sufficient.
