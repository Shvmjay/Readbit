"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, AlertCircle, Sparkles } from "lucide-react";

type Toast = { id: number; kind: "success" | "error" | "achievement"; message: string };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { ...t, id }]);
    setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), t.kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
        {toasts.map((t) => (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"}
            className="pointer-events-auto flex max-w-md items-center gap-2 rounded-xl border border-line bg-surface px-4 py-3 text-sm shadow-lift">
            {t.kind === "success" && <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden />}
            {t.kind === "error" && <AlertCircle className="h-4 w-4 shrink-0 text-danger" aria-hidden />}
            {t.kind === "achievement" && <Sparkles className="h-4 w-4 shrink-0 text-accent" aria-hidden />}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
