"use client";

import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { useT } from "@/lib/i18n-client";

export function ConfirmationDialog({
  trigger, title, body, confirmLabel, onConfirm, danger = true, confirmDisabled = false, children,
}: {
  trigger: ReactNode; title: string; body: ReactNode; confirmLabel: string; onConfirm: () => void | Promise<void>;
  danger?: boolean; confirmDisabled?: boolean; children?: ReactNode;
}) {
  const { t } = useT();
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="card fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 p-6">
          <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-muted">{body}</Dialog.Description>
          {children}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <button className="btn-secondary">{t("common.cancel")}</button>
            </Dialog.Close>
            <Dialog.Close asChild>
              <button className={danger ? "btn-danger" : "btn-primary"} disabled={confirmDisabled} onClick={() => void onConfirm()}>
                {confirmLabel}
              </button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
