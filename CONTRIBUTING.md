# Contributing to Newton

Newton is available under the [MIT License](LICENSE). Hogeschool van Amsterdam
(HvA) holds the copyright; [AUTHORS.md](AUTHORS.md) records maker attribution.
Contributions should help people investigate supplied machine information while
keeping original evidence and its limits visible.

## Find a place to help

Browse the [open issues](https://github.com/Galbaz1/newton/issues). Issues marked
[`good first issue`](https://github.com/Galbaz1/newton/labels/good%20first%20issue)
are small enough to start with; [`help wanted`](https://github.com/Galbaz1/newton/labels/help%20wanted)
marks work where outside help would be useful. Comment on an issue before taking
on a larger change so the maintainer can share context. Small corrections to code
or documentation can go straight to a pull request.

For a new bug, search existing issues first, then use the bug report template with
a minimal reproduction, expected behavior and actual behavior. For a feature or
architecture change, open a proposal issue before implementing it. Explain the
user problem and the smallest change that would solve it. An issue is a place to
agree on scope, not a promise that the idea will be accepted.

Security concerns belong in a private report under [SECURITY.md](SECURITY.md).
For community behavior concerns, use the private contact in our
[Code of Conduct](CODE_OF_CONDUCT.md). Do not put credentials, customer material,
private logs or exploit details in a public issue or pull request.

## Make a change

Start with the [README](README.md) and [developer guide](docs/development.md).
Create a branch from `main` and keep the change focused. Use the
[synthetic fixtures](tests/fixtures/README.md) for examples and tests; they are
not observations of real equipment.

Use plain typed Python and TypeScript. Keep domain logic independent of provider
SDKs and UI code. Public Python APIs need useful Google-style docstrings. Add
tests for meaningful invariants and update the documentation that describes any
changed behavior. Write code, errors and documentation in English; retain the
source language in quotations.

Run focused checks for the area you changed. Before submitting, run the relevant
commands from the [developer guide](docs/development.md) and report any check you
could not run. The repository CI runs Python tests and lint, web tests and build,
and a source-boundary check. Tests must not make paid provider calls or contact
third-party services without an explicit test setup and consent.

## Open a pull request

Describe what changed, why, how you checked it and any known limits. Link the
related issue when there is one. Include a screenshot for a visible interface
change. Keep unrelated refactors out of the same request. The maintainer reviews
changes before they enter protected `main` and may ask for a narrower scope or
additional evidence.

Check the exact files in your commit. Keep credentials, private originals,
transcripts, `.runtime`, `.env`, account databases, research archives and
proprietary code out of pull requests. The
[distribution guide](docs/distribution.md) explains the source package boundary.
Label synthetic fixtures and preserve applicable third-party notices. Check
primary documentation and licenses before adding a dependency, then update its
lockfile. Submit only material you have the right to share under this project's
MIT license.
