# Source distribution

Newton is released under the [MIT License](../LICENSE). Hogeschool van Amsterdam
(HvA) holds the copyright. [AUTHORS.md](../AUTHORS.md) records maker attribution.

The source package contains application source, tests, setup and configuration
templates, locked dependencies and developer documentation. Dependencies install
from upstream distributions. It excludes customer material, private research,
credentials, runtime state, model weights, installed environments and compiled
frontend output.

Keep private originals, datasets, transcripts, account databases, Beads state,
`.env`, `.runtime`, API credentials and proprietary legacy code outside a release.
Review the exact source list before publishing. Synthetic fixtures are test material,
not manufacturer documentation or an industrial validation set.

## Dependency notices

Preserve applicable third-party notices when changing the package format or bundling
a runtime. This repository does not distribute model weights, datasets, Docker
images or a desktop bundle.

| Component | Distribution note |
| --- | --- |
| Psycopg and psycopg-binary 3.3.6 | Installed metadata declares LGPL-3.0-only. Review bundled runtime packaging. |
| pypdfium2 5.13.0 | Wrapper, documentation and bundled PDFium components have separate terms. |
| PyTorch 2.14.0 and NumPy 2.5.3 | Installed wheels contain component-level notices beyond a top-level license label. |
| Frontend | Direct packages declare MIT, ISC or Apache-2.0; the locked graph includes MPL-2.0 declarations for Lightning CSS. |
| Weaviate 1.39.5 | Review image contents before distributing a container image. |
| PostgreSQL 18.6 | A container image can contain components beyond core PostgreSQL source. |
| ColQwen visual encoder weights | Reference the pinned revision and download route instead of shipping weights or datasets. |

Publishing wheels, containers, desktop bundles or compiled frontend assets changes
the distribution. Review their components, notices and obligations before release.
