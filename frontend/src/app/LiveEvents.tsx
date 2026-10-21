import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { fetchFleetKpis } from "../api/fleet";
import { API_BASE } from "../api/client";
import { INVALIDATES, LiveContext, type LiveStatus, useAnnounce } from "./liveContext";
import { ME_KEY } from "./queryClient";

const BATCH_MS = 1000; // many models score in the same second: refresh once

interface StreamEvent {
  type: string;
  ts?: string;
  state?: string;
  severity?: string;
  priority?: string | null;
}

/**
 * The live event stream (ARC §7.4, plan 5.3) for the whole app: each event marks the
 * affected cached reads stale so the screens refetch them; after a reconnect everything is
 * read again, because events sent while the stream was down are not replayed. A new alert
 * is announced to screen readers. `session.ended` sends the user to sign-in.
 */
export function LiveEvents({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [streamCycle, setStreamCycle] = useState<Date | null>(null);
  const pending = useRef(new Set<string>());
  const timer = useRef<number | undefined>(undefined);

  const kpis = useQuery({
    queryKey: ["fleet", "kpis"],
    queryFn: ({ signal }) => fetchFleetKpis(signal),
  });
  const kpiCycle = kpis.data?.last_cycle ? new Date(kpis.data.last_cycle) : null;

  useEffect(() => {
    let source: EventSource | null = null;
    let lostConnection = false;
    let closed = false;

    function flush() {
      const domains = [...pending.current];
      pending.current.clear();
      void client.invalidateQueries({
        predicate: (query) => domains.includes(String(query.queryKey[0])),
      });
    }

    function schedule(domains: readonly string[]) {
      domains.forEach((d) => pending.current.add(d));
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(flush, BATCH_MS);
    }

    function handle(type: string, raw: string) {
      let event: StreamEvent;
      try {
        event = JSON.parse(raw) as StreamEvent;
      } catch {
        return;
      }
      if (type === "session.ended") {
        closed = true;
        source?.close();
        client.setQueryData(ME_KEY, null);
        return;
      }
      if (type === "score.updated" && event.ts) {
        const ts = new Date(event.ts);
        setStreamCycle((previous) => (previous && previous > ts ? previous : ts));
      }
      if (type === "alert.changed" && event.state === "Active-Unacknowledged") {
        announce(
          `New ${event.severity ?? ""} alert${event.priority ? `, priority ${event.priority}` : ""}`.trim(),
        );
      }
      const domains = INVALIDATES[type];
      if (domains) schedule(domains);
    }

    function connect() {
      source = new EventSource(`${API_BASE}/events`, { withCredentials: true });
      source.onopen = () => {
        setStatus("live");
        if (lostConnection) {
          lostConnection = false;
          void client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== ME_KEY[0] });
        }
      };
      source.onerror = () => {
        if (closed) return;
        lostConnection = true;
        // EventSource retries by itself while the connection is CONNECTING; a CLOSED
        // stream (an HTTP error such as 401) is retried here after a pause.
        setStatus(source?.readyState === EventSource.CLOSED ? "offline" : "connecting");
        if (source?.readyState === EventSource.CLOSED) {
          window.setTimeout(() => {
            if (!closed) {
              void client.invalidateQueries({ queryKey: ME_KEY });
              connect();
            }
          }, 5000);
        }
      };
      for (const type of [...Object.keys(INVALIDATES), "session.ended"]) {
        source.addEventListener(type, (message: MessageEvent<string>) =>
          handle(type, message.data),
        );
      }
    }

    connect();
    return () => {
      closed = true;
      source?.close();
      window.clearTimeout(timer.current);
    };
  }, [client, announce]);

  const lastCycle = streamCycle && (!kpiCycle || streamCycle > kpiCycle) ? streamCycle : kpiCycle;
  return <LiveContext.Provider value={{ status, lastCycle }}>{children}</LiveContext.Provider>;
}
