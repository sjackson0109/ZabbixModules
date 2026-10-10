# Releasing

Releases are cut from the default branch (`work`), either from the Actions tab or by pushing a `vX.Y.Z` tag. The [release workflow](../../.github/workflows/release.yml) checks the tag, runs the standard CI checks (including the Chromium renderer suite) and the Zabbix 7.0, 7.2 and 7.4 compatibility labs, builds the packages, attests their provenance and publishes a GitHub release. Nothing is published unless every step passes.

## Version policy

- **Minor** (`1.3.0`) for a new user-facing capability; **patch** (`1.2.1`) for fixes only; **major** for a breaking change to the canonical schema, item keys or installation.
- Work lands under *Unreleased* in the changelog and is released deliberately, not on every merge.
- **Published releases are immutable.** Never delete, recreate, re-tag or overwrite a published version or its assets. A correction is a newer release.

The latest published release is 1.2.0. The next is **1.3.0**, because Monitoring → Network Explorer as the network-wide application (PR #12) is a new feature; see the [roadmap](../network-explorer/ROADMAP.md).

## 1. Prepare the version

On a branch from `work`:

```sh
python3 scripts/release.py bump 1.3.0
python3 -m pytest
```

`bump` sets the version in `VERSION`, the six frontend module manifests, the collector and the template script library, regenerates the native and LAB templates, updates the version named in the install and deployment guides, and moves the changelog's *Unreleased* entries under `## [1.3.0] - <date>`. It refuses a version that is not newer than the current one, or an empty *Unreleased* section. Review the diff, open a pull request and merge it once CI is green.

A version with a suffix, such as `1.3.0-rc.1`, is published as a pre-release.

## 2. Tag

**From GitHub (no local clone needed):** Actions → Release → Run workflow, branch `work`, version `1.3.0`. The workflow runs every check below on the head of `work`, then creates the annotated `v1.3.0` tag as Simon Jackson and publishes. It refuses a version whose tag already exists.

**Or from a clone**, on the merged commit of `work`:

```sh
git checkout work && git pull
git tag -a v1.3.0 -m "Network Explorer 1.3.0"
git push origin v1.3.0
```

## 3. What the workflow does

1. **Verify.** `scripts/release.py check v1.3.0` fails unless the tag equals `v` + `VERSION`, every component carries that version and the changelog has a `1.3.0` section. The tagged commit must be on the default branch.
2. **Checks.** The same Python, Node, Chromium and PHP jobs as pull-request CI ([checks.yml](../../.github/workflows/checks.yml)).
3. **Compatibility.** Real Zabbix 7.0, 7.2 and 7.4 labs ([compatibility.yml](../../.github/workflows/compatibility.yml), `scripts/test-compatibility.sh`). The same workflow runs nightly on `work` and on pull requests that change the frontend, widget source, templates, schemas or the lab.
4. **Publish.** Runs only when checks and all three Zabbix versions pass. Confirms the generated templates and widget assets are current, builds the archives with `scripts/package.py`, verifies `SHA256SUMS`, records a signed build-provenance attestation for every archive and `manifest.json`, and creates the GitHub release with the changelog section as its notes. Assets:
   - `network-explorer-frontend-<version>.tar`
   - `network-explorer-templates-<version>.tar`
   - `network-explorer-template-specifications-<version>.tar`
   - `network-explorer-collector-<version>.tar`
   - `manifest.json` and `SHA256SUMS`

The archives are deterministic, so building the same tag locally with `python3 scripts/package.py` gives the same checksums.

`SHA256SUMS` proves integrity: the files are the ones listed. The attestation proves provenance: the file was built by this repository's release workflow from the tagged commit. Check either or both:

```sh
sha256sum -c SHA256SUMS
gh attestation verify network-explorer-frontend-1.3.0.tar --repo sjackson0109/ZabbixModules
```

Releases up to 1.2.0 were published before attestations were added and have checksums only.

## Workflow dependencies

Every third-party action is pinned to a full commit SHA, with its release in a comment (`uses: actions/checkout@<sha> # v4.4.0`); `tests/unit/test_workflows.py` fails on an unpinned one. To update an action, resolve the new release tag to its commit (`git ls-remote --tags https://github.com/<owner>/<action> 'refs/tags/<version>*'`, taking the `^{}` line for an annotated tag) and change the SHA and the comment together. The Chromium suite's Playwright version is locked in `tests/browser/package-lock.json`.

## If a release fails

These apply only while nothing has been published.

- **Verify failed:** the tag does not match the repository. Delete the unpublished tag (`git push --delete origin v1.3.0 && git tag -d v1.3.0`), fix the version on `work` through a pull request, and tag again. A manual run fails before tagging, so it leaves nothing to delete.
- **Checks or publish failed before the release appeared:** fix the cause on `work`, delete and recreate the unpublished tag on the fixed commit. If the failure was transient, re-run the failed jobs from the Actions tab.
- **Once a release is published it is final.** `gh release create` refuses an existing release, and the release and its tag are never deleted or replaced. Fix the problem in the next patch version.
