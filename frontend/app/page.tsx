import { FileUpload } from "@/components/FileUpload";

export default function Home() {
  return (
    <main className="min-h-screen w-full px-6 py-16 sm:py-24 md:py-32">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-12">
        <header className="flex flex-col gap-4 text-center">
          <h1
            className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Data Analysis Agent
          </h1>
          <p
            className="text-base sm:text-lg text-muted-foreground"
            style={{ fontFamily: "var(--font-sans)" }}
          >
            Upload your data. Get intelligent analysis.
          </p>
        </header>
        <FileUpload />
      </div>
    </main>
  );
}
