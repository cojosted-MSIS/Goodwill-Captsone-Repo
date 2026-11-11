# Dependencies added for the web application

Recorded when a dependency is added. Versions are pinned in `pyproject.toml` where stated.

| Package | Version | License | Why | Added |
|---|---|---|---|---|
| `cryptography` | 50.0.2 (pinned) | Apache-2.0 OR BSD-3-Clause | The server opens notes sealed on a worker's device. The Python standard library has neither RSA-OAEP nor AES-GCM. | Nov 11, 2026, checkpoint 4c |

`cryptography` itself requires two packages, which are installed with it and are not used directly:

| Package | Version installed | License |
|---|---|---|
| `cffi` | 2.1.1 | MIT-0 |
| `pycparser` | 3.12 | BSD-3-Clause |

Licenses were read from each package's installed metadata (`License-Expression`).
