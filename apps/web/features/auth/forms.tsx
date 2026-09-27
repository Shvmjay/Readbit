"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n-client";
import { errorMessage } from "@/components/ui/States";
import { AuthCard, FieldError } from "./AuthCard";
import { useMe } from "@/hooks/queries";
import type { User } from "@/lib/types";

function useSchemas() {
  const { t } = useT();
  const email = z.string().trim().email(t("auth.emailInvalid"));
  const password = z.string().min(10, t("auth.passwordShort"));
  return { email, password };
}

export function LoginForm() {
  const { t } = useT();
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { email } = useSchemas();
  const schema = z.object({ email, password: z.string().min(1) });
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      await api.post<{ user: User }>("/auth/login", values);
      await qc.invalidateQueries();
      router.push(params.get("next")?.startsWith("/") ? params.get("next")! : "/app");
    } catch (e) {
      setServerError(errorMessage(e, t));
    }
  });
  return (
    <AuthCard title={t("auth.loginTitle")} subtitle={me?.guest ? t("auth.guestMerge") : undefined}>
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <div>
          <label htmlFor="email" className="label">{t("auth.email")}</label>
          <input id="email" type="email" autoComplete="email" className="input" aria-invalid={!!formState.errors.email} aria-describedby="email-err" {...register("email")} />
          <FieldError id="email-err" message={formState.errors.email?.message} />
        </div>
        <div>
          <label htmlFor="password" className="label">{t("auth.password")}</label>
          <input id="password" type="password" autoComplete="current-password" className="input" {...register("password")} />
        </div>
        {serverError && <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{serverError}</p>}
        <button type="submit" className="btn-primary w-full" disabled={formState.isSubmitting}>{t("auth.submitLogin")}</button>
      </form>
      <div className="mt-6 flex flex-col gap-2 text-sm text-muted">
        <Link href="/reset-password" className="hover:text-ink">{t("auth.forgot")}</Link>
        <span>{t("auth.noAccount")} <Link href="/register" className="font-medium text-accent">{t("auth.submitRegister")}</Link></span>
      </div>
    </AuthCard>
  );
}

export function RegisterForm() {
  const { t, locale } = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { email, password } = useSchemas();
  const schema = z.object({ email, password, display_name: z.string().max(120).optional() });
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      await api.post("/auth/register", { ...values, language: locale });
      await qc.invalidateQueries();
      router.push("/app");
    } catch (e) {
      setServerError(errorMessage(e, t));
    }
  });
  return (
    <AuthCard title={t("auth.registerTitle")} subtitle={me?.guest ? t("auth.guestMerge") : t("onboarding.privacyUser")}>
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <div>
          <label htmlFor="display_name" className="label">{t("auth.displayName")}</label>
          <input id="display_name" autoComplete="name" className="input" {...register("display_name")} />
        </div>
        <div>
          <label htmlFor="email" className="label">{t("auth.email")}</label>
          <input id="email" type="email" autoComplete="email" className="input" aria-invalid={!!formState.errors.email} aria-describedby="email-err" {...register("email")} />
          <FieldError id="email-err" message={formState.errors.email?.message} />
        </div>
        <div>
          <label htmlFor="password" className="label">{t("auth.password")}</label>
          <input id="password" type="password" autoComplete="new-password" className="input" aria-invalid={!!formState.errors.password} aria-describedby="pw-hint pw-err" {...register("password")} />
          <p id="pw-hint" className="mt-1.5 text-xs text-muted">{t("auth.passwordHint")}</p>
          <FieldError id="pw-err" message={formState.errors.password?.message} />
        </div>
        {serverError && <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{serverError}</p>}
        <button type="submit" className="btn-primary w-full" disabled={formState.isSubmitting}>{t("auth.submitRegister")}</button>
      </form>
      <p className="mt-6 text-sm text-muted">{t("auth.haveAccount")} <Link href="/login" className="font-medium text-accent">{t("auth.submitLogin")}</Link></p>
    </AuthCard>
  );
}

export function ResetForm() {
  const { t } = useT();
  const params = useSearchParams();
  const token = params.get("token");
  const { email, password } = useSchemas();
  const [done, setDone] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const schema = token ? z.object({ password }) : z.object({ email });
  const { register, handleSubmit, formState } = useForm<Record<string, string>>({ resolver: zodResolver(schema as z.ZodTypeAny) });
  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      if (token) {
        await api.post("/auth/password-reset/confirm", { token, password: values.password });
        setDone(t("auth.resetDone"));
      } else {
        await api.post("/auth/password-reset/request", { email: values.email });
        setDone(t("auth.resetSent"));
      }
    } catch (e) {
      setServerError(errorMessage(e, t));
    }
  });
  return (
    <AuthCard title={t("auth.resetTitle")} subtitle={token ? undefined : t("auth.resetBody")}>
      {done ? (
        <div role="status" className="space-y-4">
          <p className="rounded-lg bg-success/10 px-3 py-2 text-sm text-success">{done}</p>
          <Link href="/login" className="btn-secondary w-full">{t("auth.submitLogin")}</Link>
        </div>
      ) : (
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          {token ? (
            <div>
              <label htmlFor="password" className="label">{t("auth.newPassword")}</label>
              <input id="password" type="password" autoComplete="new-password" className="input" {...register("password")} />
              <FieldError id="pw-err" message={formState.errors.password?.message as string | undefined} />
            </div>
          ) : (
            <div>
              <label htmlFor="email" className="label">{t("auth.email")}</label>
              <input id="email" type="email" autoComplete="email" className="input" {...register("email")} />
              <FieldError id="email-err" message={formState.errors.email?.message as string | undefined} />
            </div>
          )}
          {serverError && <p role="alert" className="text-sm text-danger">{serverError}</p>}
          <button className="btn-primary w-full" disabled={formState.isSubmitting}>{token ? t("auth.resetSubmit") : t("auth.resetSend")}</button>
        </form>
      )}
    </AuthCard>
  );
}
