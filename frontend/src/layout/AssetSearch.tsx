import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { type Asset, fetchAllAssets } from "../api/assets";
import { assetPath, matchAssets } from "../app/assetSearch";
import { timeRangeParams } from "../app/timeRange";

function typingInAField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** PDS §2.2 asset search; "/" focuses it from anywhere (PDS §6). A combobox (WAI-ARIA). */
export function AssetSearch() {
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const navigate = useNavigate();
  const location = useLocation();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [wanted, setWanted] = useState(false); // load the list on first use only

  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
    enabled: wanted,
    staleTime: 5 * 60_000,
  });
  const results = useMemo(() => matchAssets(assets.data ?? [], text), [assets.data, text]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const slash = event.key === "/" && !event.ctrlKey && !event.metaKey;
      const ctrlK = event.key.toLowerCase() === "k" && (event.ctrlKey || event.metaKey);
      if (ctrlK || (slash && !typingInAField(event.target))) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function go(asset: Asset) {
    const carried = timeRangeParams(new URLSearchParams(location.search)).toString();
    void navigate(`${assetPath(asset)}${carried ? `?${carried}` : ""}`);
    setText("");
    setOpen(false);
    inputRef.current?.blur();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" && results.length) {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % results.length);
    } else if (event.key === "ArrowUp" && results.length) {
      event.preventDefault();
      setActive((i) => (i - 1 + results.length) % results.length);
    } else if (event.key === "Enter") {
      const chosen = results[active];
      if (chosen) {
        event.preventDefault();
        go(chosen);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
      if (!text) inputRef.current?.blur();
      setText("");
    }
  }

  const expanded = open && text.trim() !== "";
  const optionId = (i: number) => `${listId}-option-${i}`;
  return (
    <div style={{ position: "relative" }}>
      <label className="search" htmlFor={`${listId}-input`}>
        <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="6.5" />
          <path d="M16 16l4.5 4.5" />
        </svg>
        <span className="sr">Search</span>
        <input
          id={`${listId}-input`}
          ref={inputRef}
          type="search"
          placeholder="Search equipment, tags and records"
          autoComplete="off"
          role="combobox"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={expanded && results.length ? optionId(active) : undefined}
          value={text}
          onFocus={() => setWanted(true)}
          onChange={(event) => {
            setText(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
        <span className="kbd">Ctrl K</span>
      </label>
      {expanded && (
        <div id={listId} role="listbox" aria-label="Matching equipment" className="pop search-pop">
          {assets.isPending && <div className="sec s13">Loading…</div>}
          {assets.isError && <div className="sec s13">Equipment could not be loaded.</div>}
          {assets.isSuccess && results.length === 0 && (
            <div className="sec s13">Nothing matches.</div>
          )}
          {results.map((asset, i) => (
            <div
              key={asset.id}
              id={optionId(i)}
              role="option"
              tabIndex={-1}
              aria-selected={i === active}
              className={`sel-btn${i === active ? " on" : ""}`}
              onMouseDown={(event) => {
                event.preventDefault();
                go(asset);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span className="mono">{asset.code}</span>
              <span className="sec s13">{asset.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
