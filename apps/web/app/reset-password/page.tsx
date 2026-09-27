import { Suspense } from "react";
import { ResetForm } from "@/features/auth/forms";

export const metadata = { title: "Reset password" };
export default function Page() {
  return <Suspense><ResetForm /></Suspense>;
}
