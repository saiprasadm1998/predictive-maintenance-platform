import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { fetchModel } from "../../api/models";
import type { ModelDetail } from "../../api/types";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { useMe } from "../../app/session";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Skeleton } from "../fleet/FleetPage";
import {
  type BuilderDraft,
  STEPS,
  draftFromModel,
  forgetDraft,
  furthestStep,
  loadDraft,
  newDraft,
  storeDraft,
} from "./builderModel";
import {
  StepAsset,
  StepCleanse,
  StepDeploy,
  StepLimits,
  StepPeriods,
  StepTrain,
} from "./BuilderSteps";

/**
 * SCR-06 Model builder (PDS §4.6, UC-05, FR-MOD-01 to -07): six steps from the asset's
 * sensors to a deployed version. Each step checks its input before Next; the draft is kept
 * in this browser as it is edited and saved as the model's Draft version when training
 * starts; training runs as a background job that can be left and resumed here.
 */
export function BuilderPage() {
  const params = useParams();
  const [search] = useSearchParams();
  const key = params.modelId ?? "new";
  const modelId = key === "new" ? null : Number(key);
  const me = useMe();
  const model = useQuery({
    queryKey: ["models", "detail", modelId],
    queryFn: ({ signal }) => fetchModel(modelId!, signal),
    enabled: modelId !== null,
    // While a version trains, the live stream refreshes it; polling covers a stream that is down.
    refetchInterval: (q) =>
      q.state.data?.versions.some((v) => v.status === "Training") ? 3000 : false,
  });
  useBreadcrumbs(
    modelId === null
      ? [{ label: "Models", to: "/models" }, { label: "New model" }]
      : model.data
        ? [
            { label: "Models", to: "/models" },
            {
              label: `${model.data.asset_code} / ${model.data.name}`,
              to: `/models/${model.data.id}/versions/${model.data.latest.version}`,
            },
            { label: "Model builder" },
          ]
        : null,
  );

  if (!me.data || (modelId !== null && model.isPending)) return <Skeleton rows={8} />;
  if (model.isError)
    return <p role="alert">The model could not be loaded: {model.error.message}</p>;
  const userId = me.data.id;
  const initial =
    loadDraft(userId, key) ??
    (model.data ? draftFromModel(model.data) : newDraft(search.get("asset") ?? ""));
  return <Builder key={key} userId={userId} storeKey={key} model={model.data} initial={initial} />;
}

function Builder({
  userId,
  storeKey,
  model,
  initial,
}: {
  userId: number;
  storeKey: string;
  model: ModelDetail | undefined;
  initial: BuilderDraft;
}) {
  const navigate = useNavigate();
  const step = Math.min(Math.max(Number(useParams().step) || 1, 1), STEPS.length);
  const [draft, setDraft] = useState(initial);
  const [discarding, setDiscarding] = useState(false);
  const reachable = furthestStep(model, draft);
  const base = `/models/${model?.id ?? "new"}/build`;

  // Every change is kept in this browser at once (PDS §6: a draft survives navigation).
  useEffect(() => storeDraft(userId, storeKey, draft), [userId, storeKey, draft]);

  function go(to: number) {
    void navigate(`${base}/${to}`);
  }

  /** After the first save the model has an ID: the draft moves to it. */
  function saved(savedModel: ModelDetail, next: BuilderDraft, to: number) {
    storeDraft(userId, String(savedModel.id), next);
    if (storeKey === String(savedModel.id)) setDraft(next);
    else forgetDraft(userId, storeKey); // the page moves to the saved model and reads it there
    void navigate(`/models/${savedModel.id}/build/${to}`);
  }

  function done(versionNumber: number) {
    forgetDraft(userId, storeKey);
    void navigate(`/models/${model!.id}/versions/${versionNumber}`);
  }

  const latest = model?.versions[model.versions.length - 1];
  const title = model
    ? `${model.asset_code} / ${model.name}: ${latest && ["Draft", "Training", "Failed", "Validated"].includes(latest.status) ? `version ${latest.version}` : "new version"}`
    : "New model";
  const props = { draft, setDraft, model, go, saved, done };

  return (
    <div className="builder">
      <section className="panel builder-head" aria-labelledby="builder-title">
        <div>
          <h2 id="builder-title" className="panel-title">
            {title}
          </h2>
          <p className="muted small">
            Your changes are kept in this browser as you go; the model is saved when training
            starts.
          </p>
        </div>
        <button type="button" className="button" onClick={() => setDiscarding(true)}>
          Discard draft
        </button>
      </section>
      <nav aria-label="Model builder steps">
        <ol className="stepper">
          {STEPS.map((label, i) => {
            const n = i + 1;
            const text = (
              <>
                <span className="stepper-n">{n}</span> {label}
              </>
            );
            return (
              <li
                key={label}
                className={n === step ? "stepper-on" : n < step ? "stepper-done" : ""}
              >
                {n === step ? (
                  <span aria-current="step">{text}</span>
                ) : n <= reachable ? (
                  <Link to={`${base}/${n}`}>{text}</Link>
                ) : (
                  <span className="muted">{text}</span>
                )}
              </li>
            );
          })}
        </ol>
      </nav>
      {step > reachable ? (
        <section className="panel">
          <p>
            Step {step} needs the steps before it.{" "}
            <Link to={`${base}/${reachable}`}>
              Continue at step {reachable}, {STEPS[reachable - 1]!.toLowerCase()}
            </Link>
          </p>
        </section>
      ) : step === 1 ? (
        <StepAsset {...props} />
      ) : step === 2 ? (
        <StepPeriods {...props} />
      ) : step === 3 ? (
        <StepCleanse {...props} />
      ) : step === 4 ? (
        <StepTrain {...props} />
      ) : step === 5 ? (
        <StepLimits {...props} />
      ) : (
        <StepDeploy {...props} />
      )}
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title="Discard this draft?"
        consequence="The changes kept in this browser are lost. Versions already saved, trained or deployed stay as they are."
        confirmLabel="Discard"
        danger
        onConfirm={() => {
          forgetDraft(userId, storeKey);
          void navigate("/models");
        }}
      />
    </div>
  );
}
