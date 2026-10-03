"use client";

import { useRef, useState, type DragEvent } from "react";
import { FileUp } from "lucide-react";
import clsx from "clsx";
import { useT } from "@/lib/i18n-client";

const ACCEPT = ".pdf,.epub,application/pdf,application/epub+zip";

export function BookUploadDropzone({ onFile, maxMb, disabled }: { onFile: (f: File) => void; maxMb: number; disabled?: boolean }) {
  const { t } = useT();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f && !disabled) onFile(f);
  }
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}
      className={clsx("flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-colors",
        over ? "border-accent bg-accent-soft/60" : "border-line bg-surface")}>
      <span className="rounded-2xl bg-accent-soft p-3 text-accent"><FileUp className="h-7 w-7" aria-hidden /></span>
      <p className="mt-4 font-medium">{t("upload.drop")}</p>
      <p className="my-2 text-sm text-muted">{t("upload.or")}</p>
      <button type="button" className="btn-primary" onClick={() => input.current?.click()} disabled={disabled}>{t("upload.choose")}</button>
      <input ref={input} type="file" accept={ACCEPT} className="sr-only" aria-label={t("upload.choose")} data-testid="file-input"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
      <p className="mt-4 text-xs text-muted">{t("upload.subtitle", { mb: maxMb })}</p>
    </div>
  );
}
