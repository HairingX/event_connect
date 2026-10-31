# Conventions for this repository

A Python library of what devices described by their points have in common, whatever their
protocol: keys, values and their quality, how a point behaves, when it is read, and what a write or
a change sets off. Protocol packages build on it; how it works and how one is built: `README.md`.

## Comments and docstrings

Based on PEP 8 (Comments), PEP 257 (Docstring Conventions) and the Google Python Style Guide
(3.8 Comments and Docstrings).

**Docstrings describe the unit's own contract, and nothing else.**
- Every public module, class, function and method has one.
- The first line is a one-sentence summary. Add more only when a caller needs it: arguments,
  return value, exceptions raised, side effects, invariants.
- Use Google style sections (`Args:`, `Returns:`, `Raises:`) only when they say something the
  signature and type hints do not. Never repeat types; the hints carry them.
- Describe what the unit does, not who calls it, how other classes use its data, or where its
  result ends up. That knowledge belongs to those other units and goes stale here.

**Comments explain why, never what.**
- Write one only where the code cannot say it: a protocol quirk, a non-obvious constraint, the
  reason for an order of operations.
- No history: no "used to", "previously", "the old code", "this was a bug". Version control
  holds history; a regression test's name holds the reason it exists.
- No references to other files, classes, line numbers or design-document sections. They rot the
  moment the other side changes.
- No commented-out code. No TODO without an issue reference.

**Keep them short.** A comment longer than a few lines is design rationale; it belongs in
`docs/`, where it can cover several modules at once.

**Tests.** The test name states the behaviour. Add a docstring only when the reason is not
obvious from the name - one or two lines, no narrative.

## What belongs here

- **Nothing about a protocol, and no I/O.** No addresses, encodings, transports, sockets or
  sleeps: those belong to the protocol packages. A test fails for an import from outside the
  standard library.
- **What every protocol package would otherwise write again**: definitions, and the logic that
  decides from them - the scheduler, subscriptions, reachability, timing, measurements.
- **One name and one meaning per concept.** A protocol package re-exports these names rather than
  defining its own, so a point reads the same in every package built on this one.

## Versions and the packages built on this one

Every protocol package installed in one Home Assistant shares one copy of this package, so the
versions must allow one copy to serve them all.
- **Semantic versioning, strictly.** A patch fixes; a minor version adds and changes nothing that
  exists; only a major version may break something, and it is rare.
- **What is to go is deprecated first**, and removed only in the next major version.
- **A package built on this one requires a range**, never one version: `event_connect>=1.2,<2`.
- **A new major version is released only once every package built on this one is ready for it.**

## Other conventions

- pyright strict must report 0 errors (`pyright`); the configuration is in `pyproject.toml`.
  The release scripts are a project of their own: `pyright -p .github/scripts`.
- Every problem found gets a test that fails without the fix.
- Test support - fake clocks, points without a protocol, what a measurement says - lives in
  `testing/`, never in the modules that run in production.
- Test tools are pinned in `requirements-test.txt`: `pip install -e . -r requirements-test.txt`.
- Tests import the installed package, as its users do, never `src.<package>`: a packaging
  mistake then fails a test before a release.

## Releasing

**The version is the release's tag, and the draft release is never published by hand.** The
package has no version in a file: setuptools-scm works it out from the tags when it is built, so a
checkout between releases says a development version such as `0.2.1.dev3+g1a2b3c4`, and
`__version__` reads it from the installed package.

1. Merge pull requests into `main`. Release Drafter keeps a draft release proposing the next
   version: a minor bump for the label `breaking-change` or `minor`, a patch otherwise.
   **A new major version is never worked out**, as a label placed wrongly must not release one;
   type it into Release as the override.
2. Run the **Release** workflow from the Actions tab, on `main`, and choose **release
   candidate** or **final release**. It works out the version: the next release candidate of the
   open series (`0.2.0rc1` -> `0.2.0rc2`), or the final release that ends it (`0.2.0`); a draft
   naming a higher version starts a new series. Type a version only for a new major, or to
   override one worked out wrongly: canonical PEP 440, of the kind chosen.

Release refuses a version with no pull request merged since the release before it - for a
final release, the final release before it.

Release refuses any version not higher than every version tagged or on PyPI, yanked ones
included. It runs the tests on the commit it releases, tags that commit, builds, installs the
wheel and checks that `__version__` and the metadata say the version, and only then pushes the
tag - nothing is pushed to `main`. Then PyPI, then the GitHub release, marked as a pre-release
where it is one.

A release candidate's notes are written by GitHub from the pull requests merged since the
previous release candidate or final release, grouped by label as `.github/release.yml` says. A
final release's notes are the draft's: edit the draft - it lists what was merged since the last
final release - and run Release before anything else is merged, as a merge rewrites the draft.
Without a draft, GitHub writes them from the pull requests since the previous final release.

PyPI trusted publishing is bound to this repository, the file `release.yml` and the `pypi`
environment: renaming either breaks the upload. Actions are referred to by their major version;
Dependabot proposes a new major, and updates to the test tools, as pull requests.

## Branches and pull requests

- Every change goes through a branch and a pull request: `main` takes no push. A ruleset
  enforces it; its only bypass is the owner's, and only for merging a pull request. A change
  to what a user gets - the library's code or documentation - comes with its tests.
- Name every branch by the kind of change, as the release draft's labels follow the name:
  `feature/<what>` is labelled `feature request`, `fix/<what>` is labelled `bug`,
  `docs/<what>` is labelled `documentation`, and `chore/<what>` - CI, tooling, anything that
  stays in the repository - is labelled `chore`. The release notes list features and fixes;
  documentation, chores and Dependabot's `dependencies` are left out. A change to what a user
  installs, such as a new library pin, is a `fix/` or a `feature/`, never a `chore/`.
- A pull request's text describes only its own change: what it does and how it was tested. Never
  releases to come, merge order, or other repositories.
- Put `breaking-change` on a pull request that breaks the API - a `feature/` or `fix/` one, as a
  chore is left out of the notes - and `minor` on one that needs a minor bump; both give a minor
  bump, and a patch is the default. No label gives a major.
