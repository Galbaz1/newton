# Contributing to Newton

Newton is available under the [MIT License](LICENSE). Hogeschool van Amsterdam
(HvA) holds the copyright; [AUTHORS.md](AUTHORS.md) records maker attribution.

Start with the [README](README.md) and [developer guide](docs/development.md).
For a substantial change, open an issue to discuss its scope. Keep pull requests
focused and describe the behavior changed, the checks run, and any known limits.
Update the relevant documentation when behavior changes.

Use plain typed Python and TypeScript. Keep domain logic independent of provider
SDKs and UI code. Public Python APIs need useful Google-style docstrings. Add
tests for meaningful invariants. Write code, errors and documentation in English;
retain the source language in quotations.

Keep credentials, private originals, transcripts, `.runtime`, `.env`, account
databases, research archives and proprietary code out of pull requests. The
[distribution guide](docs/distribution.md) describes the source package boundary.
Label synthetic fixtures and preserve applicable third-party notices. Pin new
dependencies after checking their primary documentation and licenses. Tests must
not make paid provider calls or contact third-party services without an explicit
test setup and consent.
