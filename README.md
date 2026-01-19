Useful regex for conversion


-> -> $rightarrow$
^\d+\.\s+ -> \item
(\n\s*){2,}\\begin -> \n%\n\begin
\\\\\s*\n\\end -> \n\end
\\end\{([\w*]+)\}\n(\n\s*)+ -> \end{$1}\n%\n
([a-zA-Z.?!0-9]) {2,}([a-zA-Z0-9]) -> $1 $2