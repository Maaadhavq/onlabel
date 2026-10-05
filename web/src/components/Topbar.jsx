import { useEffect, useRef, useState } from "react";
import { ChevronDown, Code, Plus } from "./icons.jsx";

export const REPO_URL = "https://github.com/Maaadhavq/onlabel";

export default function Topbar({ samples, onOpenSample, onNew }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);
  const firstItem = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    firstItem.current?.focus();
    const away = (e) => { if (!wrap.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <header className="topbar">
      <div className="brand">
        <a className="wordmark" href="/" onClick={(e) => { e.preventDefault(); onNew(); }}>OnLabel</a>
        <span className="tagline">Checks promotional claims against the FDA label. A reviewer makes every decision.</span>
      </div>
      <nav className="nav" aria-label="Main">
        <button type="button" className="nav-link" onClick={onNew}><Plus /> New check</button>
        {samples.length > 0 && (
          <div className="menu-wrap" ref={wrap}>
            <button type="button" className="nav-link" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
              Samples <ChevronDown />
            </button>
            {open && (
              <div className="menu" role="menu" aria-label="Sample reviews">
                {samples.map((s, i) => (
                  <button
                    key={s.id}
                    ref={i === 0 ? firstItem : undefined}
                    type="button"
                    role="menuitem"
                    onClick={() => { setOpen(false); onOpenSample(s); }}
                  >
                    <span className="menu-title">{s.title}</span>
                    <span className="menu-sub">{s.nClaims} claims · {s.audience === "hcp" ? "for healthcare professionals" : "for consumers"}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <a className="nav-link" href={REPO_URL} target="_blank" rel="noreferrer"><Code /> Source</a>
      </nav>
    </header>
  );
}
