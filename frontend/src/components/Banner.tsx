import type { ReactNode } from "react";

/** A page-level notice: scope, impact and one recovery action (DESIGN.md availability banner). */
export function Banner({
  tone = "info",
  children,
}: {
  tone?: "info" | "error";
  children: ReactNode;
}) {
  return (
    <div className={`banner banner-${tone}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
