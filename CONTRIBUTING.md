# Contributing to Newton

Newton is released under the [MIT License](LICENSE). Hogeschool van Amsterdam
(HvA) holds the copyright; [AUTHORS.md](AUTHORS.md) records maker attribution.
Do not publish material from this workspace unless it belongs in the source package
described in [distribution](docs/distribution.md).

Read the README, [developer guide](docs/development.md), and the relevant Beads
issue before editing. Keep the change focused, preserve work by other contributors,
and verify the user-facing behaviour you change.

Use plain typed Python and TypeScript. Keep domain logic independent of provider
SDKs and UI code. Public Python APIs need useful Google-style docstrings. Add
tests for meaningful invariants and update the documentation that defines the
behaviour. Write authored code, errors and documentation in English; retain the
source language in quotations.

Keep credentials, private originals, worker transcripts, `.runtime`, `.env`,
account databases, Beads data, research archives and proprietary legacy code out
of distributable changes. Identify synthetic fixtures. Version a changed source
or evaluation instead of discarding earlier results. Pin new dependencies after
checking primary documentation and record the compatibility result. New cloud
services, paid calls and external actions need explicit authority.
