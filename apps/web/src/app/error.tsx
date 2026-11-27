"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <section className="empty">
      <h1>Page unavailable</h1>
      <p>Try loading this page again.</p>
      <button className="button" onClick={reset}>Retry</button>
    </section>
  );
}
