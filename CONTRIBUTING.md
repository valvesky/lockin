# Contributing

Lock-In should make starting work easier and leaving a session a deliberate choice. Keep the interface small and the commitment predictable.

1. Run `bin/test` after changing the model, backend, protocol, or metadata.
2. Run `bin/preview` for panel changes and inspect the English and Portuguese screenshots. Use the real panel and Omarchy UI components.
3. Check `omarchy plugin validate .` before publishing manifest changes.
4. Run `python3 tests/live_guard.py` explicitly when changing Hyprland integration. It briefly changes your workspace and restores it; it is never part of the default test suite.

Python uses the standard library. Keep session logic in `src/engine.py`, system integration in `src/backend.py`, and layout in QML. Put visible text in `i18n/en.json`, use `PlainLabel` for display text, and never interpolate user input into shell or Lua source. Add tests for behavioral fixes and keep emergency unlock accessible.

The public plugin ID is `valvesky.lockin`. A release updates `manifest.json` and gets a matching `vX.Y.Z` Git tag. Screenshots in `assets/` use made-up content and the reproducible preview palette. Never commit live desktop captures or session state.
