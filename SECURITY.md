# Security Policy

## Supported Versions

This repository tracks course material for UIUC SE 423 on a semester cadence. Only the **latest release** receives updates and fixes. Older releases are archived snapshots of previous semesters and are not patched.

| Version | Supported          |
| ------- | ------------------ |
| [v4.0](https://github.com/Marius-Juston/SE-423---Class-Material/releases/latest)    | :white_check_mark: |
| < [v4.0](https://github.com/Marius-Juston/SE-423---Class-Material/releases/latest)  | :x:                |

## Reporting a Vulnerability

> **Do not open a public issue for security vulnerabilities.**

If you discover a security issue — in the CI pipeline, a dependency, the GitHub Pages site, or any other part of this repository — please report it privately:

**Email**: [marius.juston@hotmail.fr](mailto:marius.juston@hotmail.fr)

Please include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce or a proof of concept, if possible.
- The affected component (CI workflow, site, LaTeX build, etc.).

You can expect an initial acknowledgment within **72 hours**. From there, we will work with you to understand the issue and determine a fix timeline. If the vulnerability is accepted, a patch will be applied to the `main` branch and a new release will be cut. If declined, we will explain the reasoning.

We ask that you practice responsible disclosure and avoid publicizing the issue until a fix has been deployed.

## Dependency Inventory

This project's attack surface is primarily its **CI/CD pipeline** (GitHub Actions) and the **GitHub Pages deployment**. Below is a full inventory of dependencies used in the build, derived from `.github/workflows/build-latex.yml`.

### CI Runner

| Component | Version / Detail |
| --------- | ---------------- |
| Runner OS | `ubuntu-latest`  |

### GitHub Actions (Third-Party)

| Action | Pinning | Purpose |
| ------ | ------- | ------- |
| `actions/checkout` | `@v4` | Source checkout |
| `actions/cache` | `@v4` | TeX Live caching |
| `actions/cache/save` | `@v4` | TeX Live cache persistence |
| `tj-actions/changed-files` | `@24d32ffd...` (SHA-pinned, v47) | Incremental build — detect changed `.tex` / `.pptx` files |

> `tj-actions/changed-files` is pinned by commit SHA to mitigate tag-substitution attacks. All other actions are GitHub first-party.

### TeX Live 2025 (LaTeX Compilation)

Installed via the CTAN network installer when `.tex` files change. Packages:

`latexmk`, `collection-latexrecommended`, `collection-latexextra`, `collection-fontsrecommended`, `collection-bibtexextra`, `amsmath`, `environ`, `minted`, `fvextra`, `catchfile`, `xcolor`, `etoolbox`, `lineno`, `dvisvgm`

### System Packages (APT)

| Package | Purpose |
| ------- | ------- |
| `python3-pygments` | Syntax highlighting for `minted` LaTeX package |
| `libreoffice`, `libreoffice-impress` | PPTX → PDF conversion (vector-preserving) |
| `fonts-dejavu`, `fonts-liberation`, `fonts-noto` | Font coverage for LibreOffice rendering |
| `mupdf-tools` | PDF processing during TikZ → SVG conversion |

### Authoring Environment

| Component | Version |
| --------- | ------- |
| Microsoft PowerPoint | Version 2603, Build 19822.20114 (Click-to-Run) |
| Operating System | Windows 11 |

Lecture slides (`.pptx`) are authored in PowerPoint and committed to the repository. The CI pipeline converts them to PDF using LibreOffice headless mode.

## Supply Chain Considerations

### GitHub Actions

The primary supply chain risk is **third-party GitHub Actions**. Mitigations in place:

- `tj-actions/changed-files` is **pinned by full commit SHA**, not a mutable tag. This prevents a compromised upstream from injecting code via tag reassignment.
- All other actions (`actions/checkout`, `actions/cache`) are GitHub first-party.
- The workflow runs with `contents: write` permission scoped to deploying built artifacts to the `artifacts` branch.

### TeX Live

Packages are fetched from CTAN mirrors at install time. The TeX Live installation is cached between runs, so packages are only downloaded when the cache key (`CACHE_VERSION`) is bumped. This limits exposure to mirror compromise to cache-miss builds.

### LibreOffice

Installed from Ubuntu's official APT repositories on each run (when PPTX files change). No third-party PPAs are used.

### GitHub Pages Site

The site in `site/` is deployed to the `artifacts` branch via a direct `git push`. There is no third-party deployment action involved. The site includes interactive tools (e.g., the color spaces visualizer) that run client-side JavaScript — contributions to `site/` should be reviewed for XSS or other client-side injection risks.

## Scope

This is a **course material repository**, not a production application. The primary security concerns are:

1. **CI pipeline integrity** — ensuring the build process is not compromised to inject malicious content into published PDFs or the course site.
2. **Supply chain attacks** — via compromised GitHub Actions, TeX Live packages, or APT packages.
3. **Site security** — XSS or injection in the GitHub Pages site served to students.
4. **Content integrity** — ensuring published materials are not tampered with.

Issues outside this scope (e.g., vulnerabilities in PowerPoint, LibreOffice, or TeX Live themselves) should be reported to their respective upstream maintainers.
