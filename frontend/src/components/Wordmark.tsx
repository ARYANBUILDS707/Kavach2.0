/** The KAVACH mark: one-stroke shield with a saffron point, beside the wordmark. Decorative
 * parts are hidden from assistive technology; the visible name is the accessible name. */
export function ShieldMark({ className = "mark" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <path
        className="mark-shield"
        d="M16 3 27 7v8.5c0 6.6-4.6 11.4-11 13.5C9.6 26.9 5 22.1 5 15.5V7Z"
      />
      <path className="mark-k" d="M12.5 10.5v11M19.5 10.5 13.5 16l6 5.5" />
      <circle className="mark-dot" cx="26.5" cy="5.5" r="4" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="wordmark">
      <ShieldMark />
      <span className="wordmark-text">KAVACH</span>
    </span>
  );
}
