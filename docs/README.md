# EchoPosture Documentation

This directory contains the maintained technical documentation for EchoPosture. The root [README](../README.md)
is the end-user landing page; the documents here are for contributors and maintainers.

## Start Here

- [Architecture](ARCHITECTURE.md): runtime components, process and thread boundaries, state flow, and extension points.
- [Release Guide](RELEASE.md): version preparation, validation, packaging, sanitization, publication, and rollback.
- [Troubleshooting](TROUBLESHOOTING.md): user and maintainer diagnosis for startup, camera, calibration, tray, and overlay failures.
- [Contributing](../CONTRIBUTING.md): development setup, change workflow, test selection, and pull request expectations.

## Repository Process Documents

These files remain at the repository root because they govern every change:

- [ROE](../ROE.md): editing, branching, commit, push, release, rollback, and backup rules.
- [Process Audit](../PROCESS_AUDIT.md): required evidence and development-log format.
- [Development Log](../DEVELOPMENT_LOG.md): chronological implementation and release evidence.
- [Remote Upload Rules](<../上传必读(英文版).md>): files that may and may not be uploaded.
- [Security Policy](../SECURITY.md): supported versions and private vulnerability reporting.

When a document disagrees with executable code or a current GitHub release, treat that as documentation drift: verify
the live behavior, fix the document, and record the correction under the repository audit rules.
