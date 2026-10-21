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
      if (event.key === "/" && !event.ctrlKey && !event.metaKey && !typingInAField(event.target)) {
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
    <div className="search">
      <label htmlFor={`${listId}-input`} className="visually-hidden">
        Search assets
      </label>
      <input
        id={`${listId}-input`}
        ref={inputRef}
        className="control search-input"
        type="search"
        placeholder="Search assets…  /"
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
      {expanded && (
        <div id={listId} role="listbox" aria-label="Matching assets" className="search-results">
          {assets.isPending && <div className="search-note">Loading assets…</div>}
          {assets.isError && <div className="search-note">Assets could not be loaded.</div>}
          {assets.isSuccess && results.length === 0 && (
            <div className="search-note">No asset matches.</div>
          )}
          {results.map((asset, i) => (
            <div
              key={asset.id}
              id={optionId(i)}
              role="option"
              tabIndex={-1}
              aria-selected={i === active}
              className={i === active ? "search-option search-option-active" : "search-option"}
              onMouseDown={(event) => {
                event.preventDefault(); // keep focus until the click lands
                go(asset);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span className="search-code">{asset.code}</span>
              <span className="search-name">{asset.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
