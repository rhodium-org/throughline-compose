# Security Policy

`throughline-compose` is a local command-line tool that reads a project directory
and fetches pinned requirement sources from their git origins into a per-user
cache. It has no server and no runtime authentication surface, and it never writes
to a source — but it does reach the network and materialise third-party content on
disk, so reports are welcome.

## Supported versions

throughline-compose is pre-1.0 (alpha). Only the latest `main` is supported; fixes
land there.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately**, not via a public issue:

- Use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  ("Report a vulnerability" under the repository's *Security* tab). Include details
  and, if possible, a minimal reproduction. The report reaches the maintainer
  (Henry Grech-Cini) privately.

Please give us a reasonable window to investigate and release a fix before any
public disclosure. We will acknowledge your report, keep you updated, and credit
you (if you wish) once a fix is available.

## Things worth reporting

The first two are this project's worst failures, and neither is obvious from
outside:

- **Any way a source can resolve to content other than its pinned ref.** Pinning is
  the whole guarantee composition offers — a composed graph must be reproducible
  run to run and machine to machine. A cache that can be poisoned, a ref that can
  be silently moved under a consumer, or a fetch that can be redirected all defeat
  it.
- **Any way a fetched source can write outside its cache directory** — a crafted
  `subdir`, a symlink in the fetched tree, or a path that escapes the source root.
- A crafted project file or requirements item that causes `tl-compose` to execute
  code or crash unsafely.
- A way the composed `check` reports a graph as sound when the underlying validator
  would reject it. A false green in a CI gate is a correctness *and* trust issue.
