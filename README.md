# UIUC SE 423: Introduction to Mechatronics (Spring 2026) 
[![Build LaTeX PDFs (TeX Live 2025) and Deploy](https://github.com/Marius-Juston/SE-423---Class-Material/actions/workflows/build-latex.yml/badge.svg)](https://github.com/Marius-Juston/SE-423---Class-Material/actions/workflows/build-latex.yml)

This repository is meant to act as a place where all the course material will be stored, compiled and shown.

While the work makes use of LaTeX, students are NOT required to use LaTeX to submit thier 

## Resources

### Animations

The animations creation is available in the following repo: https://github.com/Marius-Juston/SE423Animations 

### Template

#### Color Scheme

The color scheme follows [UIUC branding guidelines](https://brand.illinois.edu/visual-identity/color)

#### Powerpoint 

The powerpoint template was derived from [UIUC PowerPoint Template Library](https://brand.illinois.edu/resources/downloads) 

### RegEx

Useful regex for improve the LaTeX documents


|                 Regex                |       Replacement   |
|:------------------------------------:|:-------------------:|
|                 `->`                 | ` $rightarrow$ `    |
|              `^\d+\.\s+`             |     `\item `        |
|         `(\n\s*){2,}\\begin`         |   `\n%\n\begin`     |
|           `\\\\\s*\n\\end`           |     `\n\end`        |
|     `\\end\{([\w*]+)\}\n(\n\s*)+`    |  `\end{$1}\n%\n`    |
| `([a-zA-Z.?!0-9]) {2,}([a-zA-Z0-9])` |      `$1 $2`        |
| `\\begin\{minted\}\n\[(.*\n)+?\]\n+?`| `\begin{minted}`    |
| `\\begin\{figure\}(\[[a-zA-Z!]+\])?` | `\begin{figure}[H]` |
| `\\begin\{subfigure\}(\[[a-zA-Z!]+\])?` | `\begin{subfigure}[b]` |
