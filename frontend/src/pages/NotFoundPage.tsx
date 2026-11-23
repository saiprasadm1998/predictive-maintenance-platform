import { Link } from "react-router-dom";

import { PageHeader, Panel } from "../components/ui";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Panel>
        <p>
          There is no page at this address. <Link to="/fleet">Go to the overview</Link>.
        </p>
      </Panel>
    </>
  );
}
