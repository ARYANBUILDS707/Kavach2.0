import type { ButtonHTMLAttributes } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary";
  /** Shown instead of the children while an action is in flight. */
  pendingLabel?: string;
  pending?: boolean;
}

export function Button({
  variant = "primary",
  pending = false,
  pendingLabel,
  children,
  disabled,
  type = "button",
  className,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={`button button-${variant}${className ? ` ${className}` : ""}`}
      disabled={disabled === true || pending}
      aria-busy={pending || undefined}
    >
      {pending && pendingLabel ? pendingLabel : children}
    </button>
  );
}
