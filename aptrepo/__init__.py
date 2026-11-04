"""aptrepo: build a static, signed apt repository from upstream releases.

The repository is plain files (``dists/``, ``pool/``, ``index.json``,
``index.html``) that can be served by any static host. Nothing here needs a
running server.
"""

__version__ = "0.1.0"
