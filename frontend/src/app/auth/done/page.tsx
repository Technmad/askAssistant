"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { setToken } from "@/lib/auth";

function AuthDoneInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const token = searchParams.get("token");
    if (token) {
      setToken(token);
      router.replace("/");
    } else {
      router.replace("/?error=missing_token");
    }
  }, [router, searchParams]);

  return <p className="p-8 text-center">Signing you in…</p>;
}

export default function AuthDonePage() {
  return (
    <Suspense fallback={<p className="p-8 text-center">Signing you in…</p>}>
      <AuthDoneInner />
    </Suspense>
  );
}
