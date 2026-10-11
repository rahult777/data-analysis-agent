// Any unknown address, in both modes; the public snapshot build exports it as
// 404.html. Plain and neutral, with a plain link home (no next/link).
export default function NotFound() {
  return (
    <main className="min-h-screen w-full px-6 py-8 sm:py-12 md:py-16">
      <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-6 text-center">
        <h1
          className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Page not found
        </h1>
        <p className="text-base text-muted-foreground">There is nothing at this address.</p>
        <a
          href="/"
          className="inline-flex min-h-11 items-center text-base text-foreground underline underline-offset-4 hover:text-primary"
        >
          Go to the home page
        </a>
      </div>
    </main>
  );
}
