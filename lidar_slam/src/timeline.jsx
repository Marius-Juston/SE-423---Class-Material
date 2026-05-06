/* eslint-disable */
// Timeline scrubber — lets the user step through stages and frames.

const { useEffect: useEffectT, useRef: useRefT } = React;

function Timeline({
  stages, stageIdx, setStageIdx,
  step, setStep, totalSteps,
  playing, setPlaying,
}) {
  // autoplay
  useEffectT(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setStep((s) => {
        const next = s + 1;
        if (next >= totalSteps) { setPlaying(false); return totalSteps - 1; }
        return next;
      });
    }, 80);
    return () => clearInterval(id);
  }, [playing, totalSteps, setStep, setPlaying]);

  return (
    <div style={{
      display: "flex", flexDirection: "column",
      gap: 10, padding: "12px 16px",
      background: "var(--bg-1)",
      border: "1px solid var(--line)",
      borderRadius: 8,
    }}>
      {/* Stage chips */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, minHeight: 28 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button onClick={() => setStageIdx(Math.max(0, stageIdx - 1))}
                  style={btnStyle}>‹</button>
          <button onClick={() => setStageIdx(Math.min(stages.length - 1, stageIdx + 1))}
                  style={btnStyle}>›</button>
        </div>
        <div style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10.5, color: "var(--text-3)",
          minWidth: 70,
        }}>
          stage {stageIdx + 1} / {stages.length}
        </div>
        <div style={{
          flex: 1, display: "flex", gap: 4, overflowX: "auto",
          paddingBottom: 4,
        }}>
          {stages.map((s, i) => {
            const active = i === stageIdx;
            const isLoop = s.id.startsWith("loop");
            return (
              <button key={s.id}
                      onClick={() => setStageIdx(i)}
                      style={{
                        flexShrink: 0,
                        padding: "5px 10px",
                        borderRadius: 5,
                        border: `1px solid ${active ? (isLoop ? "var(--amber)" : "var(--cyan)") : "var(--line)"}`,
                        background: active
                          ? (isLoop ? "oklch(0.82 0.13 75 / 0.15)" : "oklch(0.80 0.13 220 / 0.15)")
                          : "var(--bg-2)",
                        color: active ? "var(--text-0)" : "var(--text-2)",
                        fontFamily: "JetBrains Mono, monospace",
                        fontSize: 10.5, fontWeight: active ? 600 : 400,
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                      }}>
                {String(i+1).padStart(2,"0")} · {s.id}
              </button>
            );
          })}
        </div>
      </div>

      {/* Frame scrubber */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button onClick={() => setPlaying(p => !p)} style={{
          ...btnStyle, width: 36,
          background: playing ? "var(--cyan)" : "var(--bg-3)",
          color: playing ? "var(--bg-0)" : "var(--text-0)",
          fontWeight: 700,
        }}>
          {playing ? "❚❚" : "▶"}
        </button>
        <button onClick={() => setStep(0)} style={btnStyle}>↺</button>
        <button onClick={() => setStep(Math.max(0, step - 1))} style={btnStyle}>‹</button>
        <button onClick={() => setStep(Math.min(totalSteps - 1, step + 1))} style={btnStyle}>›</button>
        <div style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10.5, color: "var(--text-3)",
          minWidth: 70,
        }}>
          t = {(step * 0.02).toFixed(2)}s
        </div>
        <input type="range" min={0} max={totalSteps - 1}
               value={step}
               onChange={(e) => setStep(parseInt(e.target.value))}
               style={{
                 flex: 1, accentColor: "oklch(0.80 0.13 220)", height: 6,
               }} />
        <div style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10.5, color: "var(--text-3)",
          minWidth: 90, textAlign: "right",
        }}>
          frame {step} / {totalSteps - 1}
        </div>
      </div>
    </div>
  );
}

const btnStyle = {
  width: 28, height: 28,
  border: "1px solid var(--line)",
  borderRadius: 5,
  background: "var(--bg-2)",
  color: "var(--text-1)",
  fontSize: 13,
  cursor: "pointer",
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  fontFamily: "Inter, sans-serif",
};

window.Timeline = Timeline;
