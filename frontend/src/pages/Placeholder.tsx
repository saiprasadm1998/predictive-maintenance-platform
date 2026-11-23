import { PageHeader, Panel } from "../components/ui";

export function Placeholder({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <Panel>
        <p className="sec">This page is being rebuilt.</p>
      </Panel>
    </>
  );
}
