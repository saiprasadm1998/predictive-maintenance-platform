/** Pages built from the established screen components, inside the Traverse page frame. */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useMe } from "../app/session";
import { HowTo, PageHeader } from "../components/ui";
import { RulesTab } from "./admin/RulesTab";
import { isModelEngineer } from "./admin/adminModel";
import { BuilderPage } from "./models/BuilderPage";
import { ModelsPage } from "./models/ModelsPage";
import { VersionPage } from "./models/VersionPage";

const SETUP = { label: "Setup overview", to: "/setup" };

function Frame({
  title,
  sub,
  crumbs,
  actions,
  children,
}: {
  title: string;
  sub?: string;
  crumbs?: { label: string; to?: string }[];
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <PageHeader title={title} sub={sub} crumbs={crumbs} actions={actions} />
      <div className="legacy">{children}</div>
    </>
  );
}

export function ModelManagementPage() {
  const me = useMe();
  return (
    <Frame
      title="Model management"
      sub="One version in service per model. Every deploy, pause, resume, retire and reject is confirmed and audited."
      crumbs={[SETUP, { label: "Models" }]}
      actions={
        <>
          <HowTo title="Model lifecycle">
            A model learns normal behaviour from a healthy training period, is tested on a later
            period it has not seen, and is deployed once its estimated false alerts are acceptable.
            Retrain it when the plant runs in a new way.
          </HowTo>
          {isModelEngineer(me.data) && (
            <Link className="btn btn-s" to="/models?apply=template">
              Apply template
            </Link>
          )}
          <Link className="btn btn-p" to="/models/new/build/1">
            New model
          </Link>
        </>
      }
    >
      <ModelsPage />
    </Frame>
  );
}

export function ModelVersionPage() {
  return <VersionPage />;
}

export function NewModelPage() {
  return <BuilderPage />;
}

export function DataQualityPage() {
  return (
    <Frame
      title="Data-quality rules"
      sub="Rules apply everywhere unless an equipment-type role or a tag has its own; the most specific wins"
      crumbs={[SETUP, { label: "Data-quality rules" }]}
      actions={
        <>
          <HowTo title="Data-quality rules">
            Sensor checks run before scoring: stale, flatline, out of range and spikes (NAMUR NE
            107). A sensor that fails is left out of the model's calculation for that cycle. Preview
            a change before saving it.
          </HowTo>
          <Link className="btn btn-s" to="/sensors">
            Sensor health →
          </Link>
        </>
      }
    >
      <RulesTab />
    </Frame>
  );
}
