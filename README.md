[![Build LaTeX PDFs (TeX Live 2025) and Deploy](https://github.com/Marius-Juston/SE-423---Class-Material/actions/workflows/build-latex.yml/badge.svg)](https://github.com/Marius-Juston/SE-423---Class-Material/actions/workflows/build-latex.yml)

Useful regex for conversion


|                 Regex                |    Replacement   |
|:------------------------------------:|:----------------:|
|                 `->`                 | ` $rightarrow$ ` |
|              `^\d+\.\s+`             |     `\item `     |
|         `(\n\s*){2,}\\begin`         |   `\n%\n\begin`  |
|           `\\\\\s*\n\\end`           |     `\n\end`     |
|     `\\end\{([\w*]+)\}\n(\n\s*)+`    |  `\end{$1}\n%\n` |
| `([a-zA-Z.?!0-9]) {2,}([a-zA-Z0-9])` |      `$1 $2`     |
| `\\begin\{minted\}\n\[(.*\n)+?\]\n+?`| `\begin{minted}` |
