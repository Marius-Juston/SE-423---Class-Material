/* eslint-disable */
// Code panel — shows lidar_slam_2d.py with the active stage's
// line range highlighted and auto-scrolled into view.

const { useEffect, useRef, useMemo, useState } = React;

// Tiny Python tokenizer good enough for highlighting. Returns an array of
// {type, text} segments per line.
const PY_KEYWORDS = new Set([
  "def","class","return","if","elif","else","for","while","break","continue",
  "import","from","as","with","try","except","finally","raise","pass","lambda",
  "yield","global","nonlocal","and","or","not","in","is","True","False","None",
  "self","async","await","del","assert"
]);
const PY_BUILTINS = new Set([
  "int","float","str","bool","list","tuple","dict","set","len","range","print",
  "isinstance","enumerate","zip","map","filter","abs","min","max","sum","open",
  "type","super","staticmethod","classmethod","property","Optional","List","Tuple"
]);

function tokenizePyLine(line) {
  const out = [];
  let i = 0;
  const n = line.length;
  // Comment first
  const hashIdx = (() => {
    // crude: ignore # inside strings — good enough for this file
    let inS = null;
    for (let k = 0; k < n; k++) {
      const c = line[k];
      if (inS) {
        if (c === inS && line[k-1] !== "\\") inS = null;
      } else {
        if (c === "'" || c === '"') inS = c;
        else if (c === "#") return k;
      }
    }
    return -1;
  })();
  const codePart = hashIdx >= 0 ? line.slice(0, hashIdx) : line;
  const commentPart = hashIdx >= 0 ? line.slice(hashIdx) : "";

  i = 0;
  const m = codePart;
  while (i < m.length) {
    const c = m[i];
    // string
    if (c === "'" || c === '"') {
      let j = i + 1;
      while (j < m.length && (m[j] !== c || m[j-1] === "\\")) j++;
      out.push({ t: "str", v: m.slice(i, Math.min(j+1, m.length)) });
      i = j + 1;
      continue;
    }
    // number
    if (/[0-9]/.test(c) && (i === 0 || !/[A-Za-z_]/.test(m[i-1]))) {
      let j = i;
      while (j < m.length && /[0-9._eE+-]/.test(m[j])) {
        // be careful with +/-: only after e/E
        if ((m[j] === "+" || m[j] === "-") && !/[eE]/.test(m[j-1])) break;
        j++;
      }
      out.push({ t: "num", v: m.slice(i, j) });
      i = j;
      continue;
    }
    // identifier
    if (/[A-Za-z_]/.test(c)) {
      let j = i;
      while (j < m.length && /[A-Za-z0-9_]/.test(m[j])) j++;
      const word = m.slice(i, j);
      let typ = "id";
      if (PY_KEYWORDS.has(word)) typ = "kw";
      else if (PY_BUILTINS.has(word)) typ = "bi";
      else if (/^[A-Z]/.test(word) && word.length > 1) typ = "cls";
      else if (m[j] === "(") typ = "fn";
      out.push({ t: typ, v: word });
      i = j;
      continue;
    }
    // decorator
    if (c === "@" && i === codePart.search(/\S/)) {
      let j = i + 1;
      while (j < m.length && /[A-Za-z0-9_.]/.test(m[j])) j++;
      out.push({ t: "dec", v: m.slice(i, j) });
      i = j;
      continue;
    }
    // punctuation/operator
    if (/[(){}\[\],.:;]/.test(c)) {
      out.push({ t: "punc", v: c }); i++; continue;
    }
    if (/[+\-*/%=<>!&|^~]/.test(c)) {
      out.push({ t: "op", v: c }); i++; continue;
    }
    // whitespace / other
    out.push({ t: "ws", v: c });
    i++;
  }
  if (commentPart) out.push({ t: "com", v: commentPart });
  return out;
}

const CODE_STYLES = {
  panel: {
    background: "var(--bg-1)",
    border: "1px solid var(--line)",
    borderRadius: 8,
    height: "100%",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    minHeight: 0,
  },
  header: {
    padding: "10px 14px",
    borderBottom: "1px solid var(--line)",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    fontSize: 12,
    color: "var(--text-1)",
    background: "var(--bg-2)",
    flexShrink: 0,
  },
  fileName: {
    fontFamily: "JetBrains Mono, monospace",
    fontWeight: 600,
    fontSize: 11.5,
    letterSpacing: 0.2,
    color: "var(--text-0)",
  },
  pill: {
    fontFamily: "JetBrains Mono, monospace",
    fontSize: 10.5,
    background: "var(--bg-3)",
    color: "var(--cyan)",
    padding: "2px 8px",
    borderRadius: 4,
    border: "1px solid var(--line)",
  },
  scroll: {
    overflow: "auto",
    flex: 1,
    minHeight: 0,
    fontFamily: "JetBrains Mono, monospace",
    fontSize: 11.5,
    lineHeight: "17px",
    paddingBottom: 200,
  },
  row: {
    display: "flex",
    paddingLeft: 0,
    paddingRight: 14,
    whiteSpace: "pre",
  },
  rowActive: {
    background: "linear-gradient(90deg, oklch(0.80 0.13 220 / 0.10), oklch(0.80 0.13 220 / 0.02))",
    boxShadow: "inset 2px 0 0 var(--cyan)",
  },
  rowFocus: {
    background: "oklch(0.80 0.13 220 / 0.18)",
    boxShadow: "inset 2px 0 0 var(--cyan)",
  },
  ln: {
    width: 44,
    color: "var(--text-3)",
    textAlign: "right",
    paddingRight: 12,
    userSelect: "none",
    flexShrink: 0,
  },
};

const TOK_COLOR = {
  kw:   "oklch(0.78 0.13 320)",   // magenta
  bi:   "oklch(0.80 0.13 75)",    // amber
  cls:  "oklch(0.82 0.10 95)",    // soft yellow
  fn:   "oklch(0.80 0.13 220)",   // cyan
  num:  "oklch(0.78 0.10 30)",    // peach
  str:  "oklch(0.74 0.10 145)",   // green
  com:  "oklch(0.50 0.012 248)",  // muted
  dec:  "oklch(0.80 0.13 75)",
  op:   "oklch(0.70 0.012 248)",
  punc: "oklch(0.70 0.012 248)",
  id:   "var(--text-0)",
  ws:   "var(--text-0)",
};

function CodeLine({ n, text, active, focus }) {
  const tokens = useMemo(() => tokenizePyLine(text), [text]);
  const style = { ...CODE_STYLES.row };
  if (focus) Object.assign(style, CODE_STYLES.rowFocus);
  else if (active) Object.assign(style, CODE_STYLES.rowActive);
  return (
    <div style={style} data-line={n}>
      <span style={CODE_STYLES.ln}>{n}</span>
      <span>
        {tokens.map((tk, i) => (
          <span key={i} style={{ color: TOK_COLOR[tk.t] || "var(--text-0)" }}>{tk.v}</span>
        ))}
      </span>
    </div>
  );
}

function CodePanel({ source, stage }) {
  const scrollRef = useRef(null);
  const lines = useMemo(() => source.split("\n"), [source]);
  const [a, b] = stage.lines;
  const [fa, fb] = stage.focus || stage.lines;

  // Scroll the focus block into view smoothly when stage changes.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const target = el.querySelector(`[data-line="${fa}"]`);
    if (!target) return;
    const t = target.offsetTop - 80;
    el.scrollTo({ top: t, behavior: "smooth" });
  }, [stage.id, fa]);

  return (
    <div style={CODE_STYLES.panel}>
      <div style={CODE_STYLES.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            width: 10, height: 10, borderRadius: 2,
            background: "var(--cyan)", boxShadow: "0 0 8px var(--cyan)",
          }} />
          <span style={CODE_STYLES.fileName}>{stage.file}</span>
          <span style={{ color: "var(--text-3)", fontFamily: "JetBrains Mono, monospace", fontSize: 11 }}>
            {lines.length} lines
          </span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <span style={CODE_STYLES.pill}>L {a}–{b}</span>
        </div>
      </div>
      <div ref={scrollRef} style={CODE_STYLES.scroll}>
        {lines.map((line, i) => {
          const n = i + 1;
          const inRange = n >= a && n <= b;
          const inFocus = n >= fa && n <= fb;
          return <CodeLine key={n} n={n} text={line} active={inRange} focus={inFocus} />;
        })}
      </div>
    </div>
  );
}

window.CodePanel = CodePanel;
