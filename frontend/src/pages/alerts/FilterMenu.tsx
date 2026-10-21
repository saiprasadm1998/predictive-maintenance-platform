import * as Popover from "@radix-ui/react-popover";
import { useId } from "react";

/** A filter button that opens a checklist (wireframe 02: "State: Active, Shelved ▾"). */
export function FilterMenu({
  name,
  options,
  chosen,
  label,
  onChange,
}: {
  name: string;
  options: readonly (readonly [string, string])[];
  chosen: readonly string[];
  label: string;
  onChange: (next: string[]) => void;
}) {
  const id = useId();
  return (
    <Popover.Root>
      <Popover.Trigger
        className="control filter-trigger"
        aria-label={`${label}. Change the ${name} filter`}
      >
        {label} <span aria-hidden="true">▾</span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="picker filter-menu" align="start" sideOffset={6}>
          <fieldset className="filter-set">
            <legend className="muted">{name}</legend>
            {options.map(([value, text]) => (
              <label key={value} className="filter-option" htmlFor={`${id}-${value}`}>
                <input
                  id={`${id}-${value}`}
                  type="checkbox"
                  checked={chosen.includes(value)}
                  onChange={(event) =>
                    onChange(
                      event.target.checked ? [...chosen, value] : chosen.filter((c) => c !== value),
                    )
                  }
                />
                {text}
              </label>
            ))}
          </fieldset>
          {chosen.length > 0 && (
            <button type="button" className="link-button" onClick={() => onChange([])}>
              Clear ({name}: all)
            </button>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
