# Contributing to SE 423 — Class Material

Thanks for your interest in improving the course materials for UIUC's **SE 423: Introduction to Mechatronics**! Whether you're a current student who spotted a typo, a TA refining a lab, or a professor adapting material for your own course — contributions of all kinds are welcome.

This repository hosts lecture slides (PowerPoint), labs and homeworks (LaTeX), figures, and a companion website. A **GitHub Actions CI pipeline** compiles everything into PDFs and deploys the site. Please read the relevant sections below before opening a pull request.

## Table of Contents

- [Quick Start](#quick-start)
- [Ways to Contribute](#ways-to-contribute)
- [Repository Structure](#repository-structure)
- [Working with Lecture Slides (PPTX)](#working-with-lecture-slides-pptx)
- [Working with Figures](#working-with-figures)
- [Working with Labs & Homeworks (LaTeX)](#working-with-labs--homeworks-latex)
- [Setting Up Your LaTeX Environment](#setting-up-your-latex-environment)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)
- [Code of Conduct](#code-of-conduct)
- [Contact](#contact)

## Quick Start

1. Fork the repository and clone your fork.
2. Create a new branch: `git checkout -b fix/lecture-5-adc-diagram`
3. Make your changes (see the relevant section for the file type you're editing).
4. Verify your changes build correctly — the CI pipeline compiles PPTX → PDF, figures → SVG, and LaTeX → PDF.
5. Commit with a clear message (see [Commit Messages](#commit-messages)).
6. Open a pull request against `main`.

## Ways to Contribute

**Fix errors** — Typos, incorrect equations, broken references, or misleading diagrams in any lecture, lab, or homework.

**Improve explanations** — Some topics (ADC configuration, SPI polarity/phase, color spaces) are known pain points for students. Clearer diagrams, worked examples, or reworded explanations are especially valuable.

**Add content** — New examples, practice problems, circuit diagrams, or code snippets relevant to the TI F28379D, sensors, actuators, or real-time control topics covered in the course.

**Improve figures** — Better quality images, new process-flow diagrams (e.g., for ADC SOC triggers and ePWM relationships), or TikZ/vector replacements for raster graphics. Figures in `Lectures/Figures/` are automatically converted to SVG for the slides.

**Enhance the course site** — Improvements to the GitHub Pages site in `site/`, including the color spaces tool or other interactive resources.

**Update animations** — The companion [SE423Animations](https://github.com/Marius-Juston/SE423Animations) repo holds the animation source. If your contribution involves animations, open the PR there instead.

## Repository Structure

```
SE-423---Class-Material/
├── Lectures/
│   ├── Slides/        # PowerPoint (.pptx) lecture slides → compiled to PDF by CI
│   └── Figures/       # Figures used in lectures → converted to SVG by CI
├── Labs/              # LaTeX source for lab handouts → compiled to PDF by CI
├── Homeworks/         # LaTeX source for homework assignments → compiled to PDF by CI
├── site/              # GitHub Pages site (HTML, interactive tools)
├── header.tex         # Shared LaTeX preamble (packages, macros)
├── icons.tex          # Icon definitions for LaTeX documents
├── syllabus.tex       # Course syllabus (LaTeX)
├── timline.tex        # Shared course timeline header (LaTeX)
├── pdf-list.txt       # List of PDFs built by CI
└── .github/workflows/ # GitHub Actions CI pipeline
```

## Working with Lecture Slides (PPTX)

Lecture slides live in `Lectures/Slides/` as PowerPoint (`.pptx`) files. The CI pipeline compiles them to PDF automatically.

### Editing slides

- Use **Microsoft PowerPoint** or **LibreOffice Impress** to edit `.pptx` files. PowerPoint is recommended for full compatibility.
- **Install the course typeface first.** Slides are set in Atkinson Hyperlegible Next; install the `.otf` files from `fonts/` or your editor will substitute another font. Keep new text in the theme font rather than picking Arial or Calibri.
- The slide template follows the [UIUC branding guidelines](https://brand.illinois.edu/visual-identity/color) and was derived from the [UIUC PowerPoint Template Library](https://brand.illinois.edu/resources/downloads). Stick to the existing color scheme and layout conventions.
- When adding new slides, follow the numbering and naming conventions already used in the folder.
- If your change involves a new figure, add the source file to `Lectures/Figures/` (see below) rather than embedding a raster image directly in the slide.

### Figures inside slides (single source)

Every picture on a slide has a source file under `Lectures/Figures/` (`svg/`, `png/`, `jpg/`, `gif/`; images that exist only in a deck live in a per-deck subfolder such as `png/L3/`). [`Lectures/Slides/figures.toml`](Lectures/Slides/figures.toml) records which file each picture comes from. The deck keeps an embedded copy so it works offline and in any viewer. **You can edit a figure on either side**, in PowerPoint or in its source file; the other side is updated for you.

**One-time setup** (per clone; needs [uv](https://docs.astral.sh/uv/getting-started/installation/)):

```bash
sh tools/install-hooks.sh
```

This enables a pre-commit hook. Whenever a commit includes a deck, a figure file or `figures.toml`, it:

- registers pictures you inserted in PowerPoint (writing their files) and drops pictures you deleted;
- copies each change the way you made it: a picture replaced or edited in PowerPoint updates its source file, and an edited or regenerated source file (e.g. a plot from SE423Animations) updates every deck that uses it;
- adds those files to the commit.

So the day-to-day workflow is simply: **edit in PowerPoint (or edit the file), save, commit.** If a picture and its file both changed since the last commit, the hook stops the commit and asks you to choose: `uv run tools/sync_deck_figures.py pull` keeps the slide, `sync` keeps the file.

Without the hook, run the same steps by hand before committing:

```bash
uv run tools/sync_deck_figures.py extract           # new/deleted pictures
uv run tools/sync_deck_figures.py auto --base HEAD  # copy changes in the direction they were made
uv run tools/sync_deck_figures.py check             # exits 1 if anything still differs
```

Updating a deck re-renders PowerPoint's PNG fallback for SVGs (needs `mutool`, from mupdf-tools) and keeps the picture's frame proportional if the new image has another aspect ratio. If you replace a picture in PowerPoint with one of another format (say an SVG with a PNG), it gets a new source file of that format. CI runs the same `auto` step before exporting the PDFs (it never reverts a slide edit) and warns when a deck and its files disagree. To use a better-named file for a picture, change its `source` in `figures.toml` (e.g. a regenerated plot in `Lectures/Figures/svg/`).

### Things to watch for

- Don't change the slide master/template unless you have a specific reason and discuss it in an issue first.
- Enable the pre-commit hook (`sh tools/install-hooks.sh`) so figure edits made in PowerPoint reach their source files (see above).
- Keep slide content concise — detailed derivations and worked examples belong in the labs and homeworks.
- Be sure to note the source of any material taken from an external website (images for example) and cite them underneath the material.

## Working with Figures

Figures in `Lectures/Figures/` are **automatically converted to SVG** by the CI pipeline for use in the lecture slides.

- Prefer vector-friendly source formats (e.g., `.svg`, `.pdf`, `.tikz`, or drawing tool formats that export cleanly) so the SVG conversion produces sharp results.
- Name figures descriptively and consistently with existing files in the folder (e.g., `adc_soc_trigger_flow.svg`, not `figure1.png`).
- If you're replacing an existing figure, keep the same filename so slide references don't break.
- Add a comment or note about the figure's source if it's derived from external material.
- **Use the course typeface.** Put `\input{fontsetup}` right after `\documentclass` in every TikZ figure and build it with `latexmk -pdflua Lectures/Figures/<figure>.tex` from the repo root. Matplotlib figures come from [SE423Animations](https://github.com/Marius-Juston/SE423Animations) and must call `course_style.apply()`. For SVGs from other tools, set text in Atkinson Hyperlegible Next and convert it to outlines.

## Working with Labs & Homeworks (LaTeX)

Labs and homeworks are written in **LaTeX** and compiled to PDF by the CI pipeline.

### General style

- Follow the existing formatting conventions in `header.tex`. Don't introduce new packages without discussing it in an issue first.
- Use `\item` for list entries rather than manually numbering items.
- Use `\begin{figure}[H]` for figure placement and `\begin{subfigure}[b]` for subfigures (these are enforced conventions — see the regex table in the README).
- Avoid double-spacing before `\begin{}` blocks. Use a `%` comment line as a visual separator instead.
- Use `$\rightarrow$` instead of `->` in text.

### Code listings

Use the `minted` package for code snippets. Specify the language explicitly (e.g., `\begin{minted}{c}` for C code targeting the F28379D).

### Colors

All colors follow the [UIUC branding guidelines](https://brand.illinois.edu/visual-identity/color). The palette is defined in `header.tex` — use those named colors rather than defining your own.

### Figures in LaTeX documents

- Prefer vector formats (TikZ, SVG converted to PDF) over raster images.
- If a figure was taken from another location, note its source in a LaTeX comment near the `\includegraphics` call.
- Place new images in the same directory as the `.tex` file that references them.

## Setting Up Your LaTeX Environment

If you're editing labs or homeworks, you'll need a working LaTeX setup. Lecture slides (PPTX) don't require LaTeX.

All documents and figures must be compiled with **LuaLaTeX** so they use the course typeface, Atkinson Hyperlegible Next (loaded from `fonts/` by `fontsetup.tex`). pdfLaTeX still compiles, but silently falls back to the old font.

### Option A: Overleaf (no local install)

Since the repo supports [Overleaf sync](https://github.com/topics/overleaf-sync), you can import the project into Overleaf to edit and preview LaTeX files without installing anything locally. This is the easiest path for small fixes. Set **Menu → Compiler → LuaLaTeX**.

### Option B: Local TeX Live

1. Install [TeX Live](https://www.tug.org/texlive/) (2025 or later) with at minimum the `latexmk`, `minted`, `tikz`, `fontspec` and `luaotfload` packages (the last two let LuaLaTeX load the course typeface).
2. Clone the repo and build a specific file:
   ```bash
   cd SE-423---Class-Material
   latexmk -pdflua -shell-escape Labs/<lab>.tex
   ```

### Verifying your build

The GitHub Actions workflow (`.github/workflows/build-latex.yml`) is the ground truth for the build. Before submitting a PR, confirm that every file listed in `pdf-list.txt` compiles without errors. The CI pipeline will catch failures, but checking locally saves review time.

## Submitting Changes

### Branching

Create a descriptive branch name that indicates the type and scope of your change:

- `fix/lecture-5-adc-diagram` — fixing something specific
- `add/homework-3-extra-problems` — adding new content
- `improve/lab-2-spi-explanation` — clarifying existing material

### Commit Messages

Write commit messages that make it easy to scan the history:

- Start with a verb: *Fix*, *Add*, *Update*, *Remove*, *Clarify*
- Reference the affected material: `Fix sign error in Lecture 10 transfer function derivation`
- Keep the first line under 72 characters. Add detail in the body if needed.

### Pull Requests

- Describe **what** changed and **why** — not just "updated Lecture 5."
- If your change addresses a known student confusion point, mention that context.
- Link any related issues.
- The CI pipeline must pass (all PDFs and SVGs build successfully) before a PR will be reviewed.
- For large changes (new lectures, restructured labs), open an issue first to discuss the approach.

## Reporting Issues

Found an error but don't want to fix it yourself? That's fine — open an [issue](https://github.com/Marius-Juston/SE-423---Class-Material/issues/new) with:

- **Which file** — e.g., "Lecture 5, slide 12" or "Homework 2, problem 3."
- **What's wrong** — the incorrect equation, misleading wording, broken figure, etc.
- **What it should say** (if you know) — suggest the correction.

For questions about course content (not errors in the materials), use [Discussions](https://github.com/Marius-Juston/SE-423---Class-Material/discussions) instead.

> **Security issues**: Do not report security vulnerabilities publicly. Email [marius.juston@hotmail.fr](mailto:marius.juston@hotmail.fr) directly.

## Code of Conduct

This project follows the [SE-423---Class-Material Code of Conduct](https://github.com/Marius-Juston/SE-423---Class-Material/blob/main/CODE_OF_CONDUCT.md). Be respectful, constructive, and collaborative. We're all here to make better course material.

## Contact

- **Marius Juston** — [marius.juston@hotmail.fr](mailto:marius.juston@hotmail.fr) / [mjuston2@illinois.edu](mailto:mjuston2@illinois.edu)

If you're a professor using or adapting this material for your own course, Marius would love to hear from you — drop a quick email!

## Attribution

This project is licensed under the [MIT License](https://github.com/Marius-Juston/SE-423---Class-Material/blob/main/LICENSE). By contributing, you agree that your work will be provided under the same license.
