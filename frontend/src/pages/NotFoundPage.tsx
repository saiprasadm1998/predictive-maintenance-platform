import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="panel placeholder">
      <h2 className="panel-title">Page not found</h2>
      <p>
        There is no screen at this address. <Link to="/fleet">Go to the fleet overview</Link>.
      </p>
    </section>
  );
}
