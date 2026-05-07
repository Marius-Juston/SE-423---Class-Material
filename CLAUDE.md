# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

Course material for **UIUC SE 423: Introduction to Mechatronics (Spring 2026)**, maintained by Marius Juston. It hosts:
- Lecture slides (`.pptx`) in `Lectures/Slides/`
- Lab handouts and homework assignments (LaTeX) in `Labs/` and `Homeworks/`
- TikZ/vector figures in `Lectures/Figures/` (auto-converted to SVG by CI)
- A GitHub Pages companion site in `site/` with interactive tools (color space visualizer, LIDAR SLAM app)

The CI pipeline (`.github/workflows/build-latex.yml`) compiles PPTX → PDF, LaTeX → PDF + HTML, and figures → SVG, then deploys to an `artifacts` branch.

## Build Commands

**Compile a single LaTeX file locally (TeX Live 2025+ required):**
```bash
latexmk -pdf Labs/Lab1.tex
```

**Full build (as CI does it, requires `-shell-escape` for minted):**
```bash
latexmk -pdflua -interaction=nonstopmode -file-line-error -halt-on-error -shell-escape -outdir=build/ <file>.tex
```

**Accessible HTML output (via make4ht):**
```bash
make4ht -s -l -c se423 -d out/ <file>.tex
```

**Figures → SVG:**
```bash
latexmk -pdf Lectures/Figures/<figure>.tex
dvisvgm --pdf --no-fonts --output=<output>.svg <figure>.pdf
```

**Alternative (no local install):** Import the project into Overleaf — the repo supports Overleaf sync.

`pdf-list.txt` lists every `.tex` file the CI compiles. All files in that list must build without errors before a PR is merged.

## Architecture

### LaTeX Document System

All LaTeX documents share a common preamble via `\input{header}` at the top of every `.tex` file. Key shared files:

- **`header.tex`** — imports all packages, defines UIUC color palette, custom macros (`\MakeAssignmentTitle`, `\Ex`), and the `\ifSEhtml` flag for PDF-vs-HTML conditional compilation
- **`icons.tex`** — icon/symbol definitions used across documents
- **`timline.tex`** — shared course timeline header included in assignments
- **`se423.cfg`** — tex4ht configuration for accessibility output (overrides inline styles to meet WCAG AA)

The `\ifSEhtml` flag switches between `minted` (PDF) and a verbatim fallback (HTML), since `minted` requires shell-escape which make4ht doesn't support in the same way.

### CI Pipeline

`.github/workflows/build-latex.yml` orchestrates the entire build:
1. Detects changed `.tex` / `.pptx` files via `tj-actions/changed-files` (incremental builds)
2. Builds PDFs with `latexmk -pdflua`
3. Converts PPTX to PDF via LibreOffice headless
4. Converts TikZ figures to SVG via `dvisvgm`
5. Generates accessible HTML via `make4ht`
6. Injects SVG gallery into the site's `index.html`
7. Deploys everything to the `artifacts` branch

### Site (`site/`)

Static HTML/CSS/JS served via GitHub Pages. Uses Three.js (via import map) for the LIDAR SLAM visualization. The `index.html` gallery is auto-populated by CI — do not manually edit the SVG injection block.

## LaTeX Conventions

Follow these precisely to keep the build and accessibility pipeline happy:

- **Figures:** always `\begin{figure}[H]`, subfigures always `\begin{subfigure}[b]`
- **Code:** use `minted` (`\begin{minted}{c}` for C, `\mintinline{c}{...}` inline)
- **Arrows:** use `$\rightarrow$`, never `->`
- **List items:** `\item`, not manual numbering
- **Blank lines:** use a `%` comment line as a visual separator before/after `\begin{}`/`\end{}` blocks, not actual blank lines
- **Colors:** use only the named UIUC palette from `header.tex`; do not define new colors
- **New packages:** don't add packages to `header.tex` without discussing it first — the accessibility pipeline and Overleaf compatibility are sensitive to package order

## Branching & Commit Style

Branch naming: `fix/lecture-5-adc-diagram`, `add/homework-3-extra-problems`, `improve/lab-2-spi-explanation`

Commit messages: start with a verb (*Fix*, *Add*, *Update*, *Clarify*) and reference the affected material. Example: `Fix sign error in Lecture 10 transfer function derivation`

## Known Content Issues (do not fix without discussion)

- L5: ADC SOC trigger / ePWM relationship diagram is incomplete
- L6-7: SPI polarity/phase diagram (slide 49) is confusing
- L17: Should cover HSL not HSV; blob/shape/area filtering missing
- L19 Extra: Dubins & Reeds-Sheep visualization is incorrect
- L20: Spacing/flow is confusing — rewrite candidate
- L24-25 (SLAM): High-priority over L22-23 Computer Vision content
