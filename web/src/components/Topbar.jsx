export default function Topbar({ labels, draft, setDraft, onCheck, canCheck, busy }) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="wordmark">OnLabel</span>
        <span className="tagline">Checks promotional claims against the FDA label. A reviewer makes every decision.</span>
      </div>
      <div className="controls">
        <label className="field-label" htmlFor="label-pick">Label</label>
        <select id="label-pick" className="select" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })}>
          <option value="">Detect from the copy</option>
          {labels.map((l) => (
            <option key={l.key} value={l.key}>{l.drug}, version {l.version}</option>
          ))}
        </select>
        <span className="field-label" id="audience-label">Audience</span>
        <div className="seg" role="group" aria-labelledby="audience-label">
          {[["consumer", "Consumer"], ["hcp", "HCP"]].map(([value, text]) => (
            <button key={value} type="button" aria-pressed={draft.audience === value} onClick={() => setDraft({ ...draft, audience: value })}>
              {text}
            </button>
          ))}
        </div>
        <button type="button" className="btn btn-primary" onClick={onCheck} disabled={!canCheck}>
          {busy ? "Checking…" : "Check copy"}
        </button>
      </div>
    </header>
  );
}
