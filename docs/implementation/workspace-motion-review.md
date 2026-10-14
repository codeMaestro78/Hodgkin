# Workspace motion review

Scope: research panel/composer entrances, selection markers, activity feedback,
and the existing independent report/evidence/history scrolling layout.

| Before | After | Why |
| --- | --- | --- |
| JavaScript-updated entrance transforms, 280 ms, opacity 0.35 | Native full-transform/opacity keyframes, 200 ms, opacity 0.7 | Preserve readability and avoid a JavaScript update on every animation frame |
| Unbounded cumulative entrance staggering | 20 ms spacing capped at 60 ms | Additional evidence must not wait behind a long reveal sequence |
| Hover movement gated only by hover capability | Also require a fine pointer | Avoid sticky hover motion on touch/hybrid interfaces |

## Verdict

Performance: entrance effects use only transform/opacity and do not retain fill
or inline styles. Cleanup cancels effects on dependency changes, media-query
changes and unmount. The existing interruptible sliding indicator remains native.

Accessibility: keyboard navigation remains immediate. Reduced-motion users see
the final state without movement. The busy activity line stops on terminal state;
it indicates activity, not fabricated progress percentages.

Approve this bounded motion change. Unit regressions cover cleanup, keyframe
properties, delay limits, keyboard and reduced-motion behavior. Isolated browser
checks exercised rapid tab changes, reduced-motion keyboard selection and a
390-pixel viewport without horizontal overflow. No production frame-time or
generation-latency improvement is claimed. Review motion feel on a real touch
device before release; browser fixtures do not replace that check.

Native behavior reference: [Element.animate](https://developer.mozilla.org/en-US/docs/Web/API/Element/animate)
and [Animation.cancel](https://developer.mozilla.org/en-US/docs/Web/API/Animation/cancel).
