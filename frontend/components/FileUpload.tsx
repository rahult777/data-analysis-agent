"use client";

import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  FileSpreadsheet,
  FileText,
  Loader2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { uploadFile } from "@/lib/api";
import { cn } from "@/lib/utils";

const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024;
const VALID_EXTENSIONS: string[] = [".csv", ".xls", ".xlsx"];
const CSV_PREVIEW_BYTES = 2048;
const BYTES_PER_KB = 1024;
const BYTES_PER_MB = BYTES_PER_KB * BYTES_PER_KB;

type UserType = "business_owner" | "data_analyst" | "data_scientist";
type ErrorKind = "user" | "api";

interface UploadError {
  type: ErrorKind;
  message: string;
}

interface UserTypeOption {
  value: UserType;
  label: string;
  description: string;
}

const USER_TYPE_OPTIONS: UserTypeOption[] = [
  {
    value: "business_owner",
    label: "Business Owner",
    description: "I want clear findings and recommended actions",
  },
  {
    value: "data_analyst",
    label: "Data Analyst",
    description: "I want statistical rigor and full methodology",
  },
  {
    value: "data_scientist",
    label: "Data Scientist",
    description:
      "I want complete transparency including all code and decisions",
  },
];

function formatBytes(bytes: number): string {
  if (bytes < BYTES_PER_KB) return `${bytes} B`;
  if (bytes < BYTES_PER_MB) return `${(bytes / BYTES_PER_KB).toFixed(1)} KB`;
  return `${(bytes / BYTES_PER_MB).toFixed(1)} MB`;
}

function getExtension(filename: string): string {
  const idx = filename.lastIndexOf(".");
  return idx === -1 ? "" : filename.slice(idx).toLowerCase();
}

export function FileUpload() {
  const router = useRouter();

  const [file, setFile] = useState<File | null>(null);
  const [dragCounter, setDragCounter] = useState<number>(0);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [error, setError] = useState<UploadError | null>(null);
  const [context, setContext] = useState<string>("");
  const [userType, setUserType] = useState<UserType | null>(null);
  const [columnCount, setColumnCount] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const isDragging = dragCounter > 0;

  useEffect(() => {
    if (!file) {
      setColumnCount(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const text = await file.slice(0, CSV_PREVIEW_BYTES).text();
        const firstLine = text.split("\n")[0] ?? "";
        const count = firstLine.split(",").length;
        if (!cancelled) setColumnCount(count);
      } catch {
        if (!cancelled) setColumnCount(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [file]);

  function handleFileSelection(selectedFile: File): void {
    const ext = getExtension(selectedFile.name);
    if (!VALID_EXTENSIONS.includes(ext)) {
      setError({
        type: "user",
        message: `Unsupported file type. Please upload ${VALID_EXTENSIONS.join(", ")}.`,
      });
      return;
    }
    if (selectedFile.size === 0) {
      setError({
        type: "user",
        message: "This file is empty. Please choose a file with data.",
      });
      return;
    }
    if (selectedFile.size > MAX_FILE_SIZE_BYTES) {
      setError({
        type: "user",
        message: `File exceeds the ${formatBytes(MAX_FILE_SIZE_BYTES)} limit.`,
      });
      return;
    }
    setError(null);
    setFile(selectedFile);
    setColumnCount(null);
  }

  function handleClick(): void {
    if (isUploading) return;
    inputRef.current?.click();
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
  }

  function handleDragEnter(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragCounter((c) => c + 1);
  }

  function handleDragLeave(): void {
    setDragCounter((c) => c - 1);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragCounter(0);
    if (isUploading) return;
    if (!event.dataTransfer.files || event.dataTransfer.files.length === 0) {
      return;
    }
    handleFileSelection(event.dataTransfer.files[0]);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (isUploading) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      inputRef.current?.click();
    }
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>): void {
    if (!event.target.files || event.target.files.length === 0) return;
    handleFileSelection(event.target.files[0]);
  }

  function handleChooseDifferent(): void {
    if (isUploading) return;
    if (inputRef.current) inputRef.current.value = "";
    setFile(null);
    setError(null);
  }

  function handleToggleUserType(value: UserType): void {
    setUserType((prev) => (prev === value ? null : value));
  }

  async function handleUpload(): Promise<void> {
    if (!file || isUploading) return;
    setIsUploading(true);
    setError(null);
    try {
      const response = await uploadFile(
        file,
        context || undefined,
        userType || undefined,
      );
      localStorage.setItem(
        `session_id_${response.analysis_id}`,
        response.session_id,
      );
      router.push(`/analysis/${response.analysis_id}`);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Upload failed. Please try again.";
      setError({ type: "api", message });
    } finally {
      setIsUploading(false);
    }
  }

  const fileExt = file ? getExtension(file.name) : "";
  const FileIcon = fileExt === ".csv" ? FileText : FileSpreadsheet;

  return (
    <div className="flex flex-col gap-8">
      <motion.div
        role="button"
        tabIndex={0}
        aria-label="Upload data file by dropping or clicking"
        aria-disabled={isUploading}
        onClick={handleClick}
        onDragOver={handleDragOver}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onKeyDown={handleKeyDown}
        animate={{
          borderColor: isDragging
            ? "var(--primary)"
            : "color-mix(in oklch, var(--border) 60%, transparent)",
          backgroundColor: isDragging
            ? "color-mix(in oklch, var(--primary) 5%, transparent)"
            : "color-mix(in oklch, var(--card) 40%, transparent)",
          scale: isDragging ? 0.99 : 1,
        }}
        transition={{ duration: 0.2, ease: "easeOut" }}
        className={cn(
          "rounded-md border min-h-[200px] md:min-h-[300px] flex flex-col items-center justify-center gap-6 text-center px-6 py-10 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          isUploading && "opacity-50 cursor-not-allowed pointer-events-none",
        )}
      >
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card/40 px-3 py-1 text-xs text-muted-foreground">
            <FileText className="size-3.5" aria-hidden />
            CSV
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card/40 px-3 py-1 text-xs text-muted-foreground">
            <FileSpreadsheet className="size-3.5" aria-hidden />
            XLSX
          </span>
        </div>
        <motion.h2
          animate={{
            color: isDragging ? "var(--primary)" : "var(--foreground)",
          }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          className="italic text-2xl md:text-3xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Drop your dataset
        </motion.h2>
        <p className="text-sm text-muted-foreground max-w-sm">
          Drag and drop, or click to browse. Up to{" "}
          {formatBytes(MAX_FILE_SIZE_BYTES)}.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={VALID_EXTENSIONS.join(",")}
          className="hidden"
          aria-hidden="true"
          tabIndex={-1}
          onChange={handleInputChange}
        />
      </motion.div>

      <div className="flex flex-col gap-2">
        <Label
          htmlFor="upload-context"
          className="text-xs uppercase tracking-[0.2em] text-muted-foreground"
        >
          Context (optional)
        </Label>
        <Textarea
          id="upload-context"
          value={context}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
            setContext(event.target.value)
          }
          placeholder="Tell us about your data: what it represents, what you're trying to learn."
          className="min-h-[120px] bg-card/40 border-border/60"
        />
      </div>

      <div className="flex flex-col gap-3">
        <Label className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Who&apos;s analyzing this? (optional)
        </Label>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {USER_TYPE_OPTIONS.map((option) => {
            const selected = userType === option.value;
            return (
              <motion.button
                key={option.value}
                type="button"
                onClick={() => handleToggleUserType(option.value)}
                aria-pressed={selected}
                animate={{
                  borderColor: selected
                    ? "var(--primary)"
                    : "color-mix(in oklch, var(--border) 60%, transparent)",
                  backgroundColor: selected
                    ? "color-mix(in oklch, var(--primary) 5%, transparent)"
                    : "color-mix(in oklch, var(--card) 40%, transparent)",
                }}
                transition={{ duration: 0.2, ease: "easeOut" }}
                className="border rounded-md p-4 min-h-[88px] text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <p className="text-sm font-medium">{option.label}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {option.description}
                </p>
              </motion.button>
            );
          })}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {file !== null && (
          <motion.div
            key="file-preview"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 16 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="border border-border bg-card rounded-md p-5 md:p-6"
          >
            <div className="flex flex-col md:flex-row md:items-center gap-5">
              <div className="flex items-center justify-center size-12 rounded-md border border-border/60 shrink-0">
                <FileIcon
                  className="size-5 text-muted-foreground"
                  aria-hidden
                />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{file.name}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {formatBytes(file.size)}
                  {columnCount !== null && ` · approx. ${columnCount} columns`}
                </p>
              </div>
              <div className="flex flex-col gap-2 md:w-48">
                <Button
                  type="button"
                  size="lg"
                  className="w-full"
                  disabled={isUploading}
                  onClick={handleUpload}
                >
                  {isUploading ? (
                    <>
                      <motion.span
                        className="inline-flex"
                        animate={{ rotate: 360 }}
                        transition={{
                          repeat: Infinity,
                          duration: 1,
                          ease: "linear",
                        }}
                      >
                        <Loader2 className="size-4" aria-hidden />
                      </motion.span>
                      Uploading…
                    </>
                  ) : (
                    "Start Analysis"
                  )}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full"
                  disabled={isUploading}
                  onClick={handleChooseDifferent}
                >
                  Choose a different file
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence initial={false}>
        {error !== null && (
          <motion.div
            key={`error-${error.type}`}
            role="alert"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className={cn(
              "flex items-start gap-3 rounded-md border px-4 py-3 text-sm",
              error.type === "user"
                ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
                : "border-red-500/30 bg-red-500/10 text-red-200",
            )}
          >
            <AlertTriangle className="size-4 mt-0.5 shrink-0" aria-hidden />
            <p>{error.message}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
