"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, ShieldCheck } from "lucide-react";
import { uploadWithProgress } from "@/lib/api";
import type { Book } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { useBook, useMe, useMeta } from "@/hooks/queries";
import { PageHeader } from "@/components/layout/AppShell";
import { ErrorState, ProgressBar } from "@/components/ui/States";
import { BookUploadDropzone } from "@/features/upload/BookUploadDropzone";
import { ProcessingStatus } from "@/features/upload/ProcessingStatus";
import { formatBytes } from "@/lib/format";

type Phase = "idle" | "selected" | "uploading" | "uploaded";

export default function UploadPage() {
  const { t } = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: meta } = useMeta();
  const { data: me } = useMe();
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [pct, setPct] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [bookId, setBookId] = useState<string | null>(null);
  const maxMb = meta?.limits.max_upload_size_mb ?? 50;

  async function start(f: File) {
    setFile(f);
    setError(null);
    setPhase("selected");
    if (f.size > maxMb * 1024 * 1024) {
      setError(new Error(t("errors.file_too_large")));
      return;
    }
    setPhase("uploading");
    try {
      const res = await uploadWithProgress<{ book: Book; duplicate: boolean }>(f, setPct);
      setPhase("uploaded");
      qc.invalidateQueries({ queryKey: ["books"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (res.data.duplicate) {
        router.push(`/app/books/${res.data.book.id}`);
        return;
      }
      setBookId(res.data.book.id);
    } catch (e) {
      setError(e);
      setPhase("idle");
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title={t("upload.title")} subtitle={t("upload.subtitle", { mb: maxMb })} />
      {!bookId && <BookUploadDropzone onFile={start} maxMb={maxMb} disabled={phase === "uploading"} />}
      {file && (
        <div className="card flex items-center gap-4 p-4" data-testid="upload-progress">
          <FileText className="h-8 w-8 shrink-0 text-accent" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{file.name}</p>
            <p className="text-xs text-muted">{formatBytes(file.size)} · {(file.name.split(".").pop() || "").toUpperCase()} · {t(`upload.state${phase === "uploading" ? "Uploading" : phase === "uploaded" ? "Uploaded" : "Selected"}`)}</p>
            {phase === "uploading" && <ProgressBar className="mt-2" value={pct} label={t("upload.stateUploading")} />}
          </div>
        </div>
      )}
      {error != null && <ErrorState error={error} />}
      {bookId && <UploadedBook id={bookId} onAnother={() => { setBookId(null); setFile(null); setPhase("idle"); }} />}
      <p className="flex items-start gap-2 text-sm text-muted"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />{t("upload.rights")}</p>
      {me?.guest && <p className="text-sm text-muted">{t("upload.guestRetention", { hours: meta?.limits.guest_retention_hours ?? 24 })}</p>}
    </div>
  );
}

function UploadedBook({ id, onAnother }: { id: string; onAnother: () => void }) {
  const { t } = useT();
  const { data } = useBook(id);
  if (!data) return null;
  return (
    <div className="space-y-4">
      <ProcessingStatus book={data.book} />
      <div className="flex gap-2">
        {data.book.processing_status === "ready" && <Link href={`/app/books/${id}`} className="btn-primary" data-testid="open-book">{t("upload.open")}</Link>}
        <button className="btn-secondary" onClick={onAnother}>{t("upload.another")}</button>
      </div>
    </div>
  );
}
