# Releasing

Releases are cut from the default branch (`work`), either from the Actions tab or by pushing a `vX.Y.Z` tag. The [release workflow](../../.github/workflows/release.yml) checks the tag, runs the full CI suite, builds the packages and publishes a GitHub release. Nothing is published unless every step passes.

## 1. Prepare the version

On a branch from `work`:

```sh
python3 scripts/release.py bump 1.2.0
python3 -m pytest
```

`bump` sets the version in `VERSION`, the six frontend module manifests, the collector and the template script library, regenerates the native and LAB templates, updates the version named in the install and deployment guides, and moves the changelog's *Unreleased* entries under `## [1.2.0] - <date>`. It refuses a version that is not newer than the current one, or an empty *Unreleased* section. Review the diff, open a pull request and merge it once CI is green.

A version with a suffix, such as `1.3.0-rc.1`, is published as a pre-release.

## 2. Tag

**From GitHub (no local clone needed):** Actions → Release → Run workflow, branch `work`, version `1.2.0`. The workflow runs every check below on the head of `work`, then creates the annotated `v1.2.0` tag as Simon Jackson and publishes. It refuses a version whose tag already exists.

**Or from a clone**, on the merged commit of `work`:

```sh
git checkout work && git pull
git tag -a v1.2.0 -m "Network Explorer 1.2.0"
git push origin v1.2.0
```

## 3. What the workflow does

1. **Verify.** `scripts/release.py check v1.2.0` fails unless the tag equals `v` + `VERSION`, every component carries that version and the changelog has a `1.2.0` section. The tagged commit must be on the default branch.
2. **Checks.** The same Python, Node and PHP jobs as pull-request CI.
3. **Publish.** Confirms the generated templates and widget assets are current, builds the archives with `scripts/package.py`, verifies `SHA256SUMS`, and creates the GitHub release with the changelog section as its notes. Assets:
   - `network-explorer-frontend-<version>.tar`
   - `network-explorer-templates-<version>.tar`
   - `network-explorer-template-specifications-<version>.tar`
   - `network-explorer-collector-<version>.tar`
   - `manifest.json` and `SHA256SUMS`

The archives are deterministic, so building the same tag locally with `python3 scripts/package.py` gives the same checksums.

## If a release fails

- **Verify failed:** the tag does not match the repository. Delete the tag (`git push --delete origin v1.2.0 && git tag -d v1.2.0`), fix the version on `work` through a pull request, and tag again.
- **Checks or publish failed:** fix the cause on `work`, delete and recreate the tag on the fixed commit. If the failure was transient, re-run the failed jobs from the Actions tab.
- A published release is never overwritten: `gh release create` fails if the release exists. To replace one, delete the release and its tag first, or release the next patch version.
