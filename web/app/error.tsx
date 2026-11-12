"use client";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="wrap">
      <h1>The live view hit an error</h1>
      <p className="meta">{error.message || "Unexpected error."} The run itself is not affected.</p>
      <button className="btn" onClick={() => reset()}>Try again</button>
    </main>
  );
}
