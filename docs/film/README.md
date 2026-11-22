# AuditGym launch film (25 s)

`docs/auditgym_film.mp4`: 1920×1080, 30 fps, 25 s, with sound. Made with the onetake skill
(github.com/feitangyuan/onetake, PolyForm Noncommercial 1.0.0; `motion.js` is its move library).

Concept "one tick": the auditor's green tick is the subject of the whole film. It is drawn, pulls back into
the margin of a ledger, watches a red pencil inject three errors, refuses the trap (same amount, a
subscription), lands on the real duplicate, sheds three evidence chips that become a finding, is
scored (+0,969), and returns as the check of `CHECK PASSED` and above the wordmark.

Acceptance oracle (`verify_promo.py`): cadence CV 0.28, still 50 %, 3 bursts, carry 1.00, audio peak −8 dBFS — PASS.
Sound: synthesised palette (`score.py`), no third-party music. Fonts: OFL (see FONT_LICENSES.txt).

Rebuild: `python3 <onetake>/scripts/render.py comp.html --out film.mp4 --sfx sfx.wav` (after `python3 score.py`).
