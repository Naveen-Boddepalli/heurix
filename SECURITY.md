# Security Policy

## Supported versions

Security fixes go into the latest release on [PyPI](https://pypi.org/project/heurix/). Older releases are not patched, so upgrade before reporting an issue you found in an older version.

## Reporting a vulnerability

Please don't open a public issue for a security problem. Report it privately through GitHub instead:

1. Go to the [Security tab](https://github.com/Naveen-Boddepalli/heurix/security) of this repository.
2. Click **Report a vulnerability** and fill in the form.

Include the Heurix version (`hx --version`), the command you ran, and a minimal repository or workflow that shows the problem. You should get a reply within a week. Once a fix is released, the advisory is published with credit to you unless you'd rather stay anonymous.

## What counts as a vulnerability

Heurix reads a repository and writes YAML into it, so the issues we most want to hear about are:

- Generated workflows or manifests that are less safe than they claim, for example a secret exposed to a job or pod that shouldn't see it, or missing `permissions` / `securityContext` hardening.
- `hx check --security` missing a case its rules are meant to catch, in a way that could hide a real attack.
- Writing files outside the target repository (path traversal, symlinks), or running code from the scanned repository.
- `hx pin` resolving a tag to a commit from a different repository than the one in `uses:`.

Problems in a workflow you wrote yourself, or in third-party actions Heurix references, belong with those projects.
