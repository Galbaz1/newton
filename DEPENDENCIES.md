# Dependencies and licensing

The exact Python, frontend and optional-service dependencies are recorded in the
respective `uv.lock` and `package-lock.json` files. Installation downloads them
from their registries; this repository does not vendor their packages, binaries,
model weights or container images. Their upstream licenses continue to apply.

Compose pins PostgreSQL and Weaviate by version and image digest. Review the terms
for the exact image before redistributing images or enabling licensed features.
The optional encoder requires separately obtained model weights and their model
card/license. An available download is not blanket permission to redistribute it.

The included text/CSV fixtures are authored synthetic examples. Customer datasets,
third-party manuals, screenshots, recordings, private research archives and model
weights are not part of this source distribution.

Newton software and accompanying project documentation use the [MIT License](LICENSE).
Copyright (c) 2026 Hogeschool van Amsterdam. Created by
[Wonder Why AI — Fausto Albers](AUTHORS.md). Repository access remains private;
third-party dependencies and customer material retain their own terms.
