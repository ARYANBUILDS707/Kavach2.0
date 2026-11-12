// Decorative line illustrations in the reference style: ink outlines, cream fills, one accent.
// All are aria-hidden; the surrounding text carries the meaning. None depicts a score or gauge.

const svgProps = { "aria-hidden": true, focusable: false } as const;

/** Hero art: the shield mark large, on a dotted panel drawn by CSS. */
export function HeroShield() {
  return (
    <svg className="ill ill-hero" viewBox="0 0 320 320" {...svgProps}>
      <path
        className="ill-cream ill-ink-stroke"
        d="M160 34 262 72v84c0 66-44 112-102 132C102 268 58 222 58 156V72Z"
      />
      <path className="ill-ink-stroke ill-thick" d="M128 108v104M196 108l-58 52 58 52" />
      <circle className="ill-saffron" cx="258" cy="58" r="30" />
      <circle className="ill-saffron" cx="40" cy="282" r="14" />
    </svg>
  );
}

/** Controlled submission: a message bubble passing into the shield. */
export function SubmitIllustration() {
  return (
    <svg className="ill" viewBox="0 0 240 120" {...svgProps}>
      <rect className="ill-cream ill-ink-stroke" x="8" y="22" width="120" height="62" rx="16" />
      <path className="ill-cream ill-ink-stroke" d="M34 84l-6 22 24-22" />
      <circle className="ill-ink" cx="46" cy="53" r="6" />
      <circle className="ill-ink" cx="68" cy="53" r="6" />
      <circle className="ill-ink" cx="90" cy="53" r="6" />
      <path className="ill-ink-stroke" d="M140 53h26m-9-9 9 9-9 9" />
      <path
        className="ill-cream ill-ink-stroke"
        d="M204 18 230 28v22c0 18-11 30-26 36-15-6-26-18-26-36V28Z"
      />
      <path className="ill-ink-stroke" d="M193 52l8 8 14-16" />
    </svg>
  );
}

/** Incident history: a stack of records under a magnifier. */
export function HistoryIllustration() {
  return (
    <svg className="ill" viewBox="0 0 240 120" {...svgProps}>
      <rect className="ill-cream ill-ink-stroke" x="20" y="14" width="150" height="26" rx="10" />
      <rect className="ill-cream ill-ink-stroke" x="20" y="48" width="150" height="26" rx="10" />
      <rect className="ill-cream ill-ink-stroke" x="20" y="82" width="150" height="26" rx="10" />
      <path className="ill-ink-stroke" d="M34 27h60M34 61h80M34 95h50" />
      <circle className="ill-cream ill-ink-stroke ill-thick" cx="188" cy="62" r="24" />
      <path className="ill-ink-stroke ill-thick" d="M205 79l22 22" />
    </svg>
  );
}

/** Evidence and analysis status: stacked stage layers, one marked as missing. */
export function StagesIllustration() {
  return (
    <svg className="ill" viewBox="0 0 240 120" {...svgProps}>
      <path className="ill-cream ill-ink-stroke" d="M120 10 214 40 120 70 26 40Z" />
      <path className="ill-ink-stroke" d="M26 60l94 30 94-30" />
      <path className="ill-ink-stroke ill-dashed" d="M26 80l94 30 94-30" />
      <circle className="ill-saffron" cx="120" cy="40" r="9" />
    </svg>
  );
}

/** System readiness: a status panel with a heartbeat line. */
export function SystemIllustration() {
  return (
    <svg className="ill" viewBox="0 0 240 120" {...svgProps}>
      <rect className="ill-cream ill-ink-stroke" x="20" y="16" width="200" height="88" rx="16" />
      <path className="ill-ink-stroke ill-thick" d="M36 64h40l12-24 18 44 14-30 10 10h74" />
      <circle className="ill-saffron" cx="196" cy="36" r="8" />
    </svg>
  );
}
