"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useState, type ReactNode } from "react";
import { I18nProvider } from "@/lib/i18n-client";
import { ApiError } from "@/lib/api";
import type { Language } from "@/lib/types";
import { ToastProvider } from "@/components/ui/Toast";

export function Providers({ locale, children }: { locale: Language; children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: (count, err) => err instanceof ApiError && err.retryable && err.status !== 429 && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale={locale}>
        <Tooltip.Provider delayDuration={300}>
          <ToastProvider>{children}</ToastProvider>
        </Tooltip.Provider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
