import { Suspense } from "react";
import { LoginForm } from "@/features/auth/forms";

export const metadata = { title: "Sign in" };
export default function Page() {
  return <Suspense><LoginForm /></Suspense>;
}
