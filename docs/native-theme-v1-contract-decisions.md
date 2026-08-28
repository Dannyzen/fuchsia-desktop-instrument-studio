# NativeThemeV1 first-release contract decisions

Every packaged theme supplies `light`, `dark`, and `high-contrast`. A compiled snapshot is immutable, executable-free, host-compiled, and restart-to-apply. Unknown required schema or profile versions fail closed; optional namespaced metadata may evolve additively.

The semantic taxonomy distinguishes surfaces, text, borders, selection, confirmed focus, and success/warning/error status. Confirmed focus is distinct from selection. Status is not conveyed by color alone: semantic status asset IDs are required and deterministically fall back to built-in assets.

Ordinary variants target WCAG 2.2 AA: 4.5 for normal text and 3.0 for large text, UI boundaries, selection, and focus. High-contrast targets are 7.0 for normal text and 4.5 for large text, selection, and focus. Reduced motion has a zero-duration deterministic selection while essential state transitions remain available.

Typography includes proportional and monospace selections, size, weight, and line height. Geometry includes spacing, radius, density, and responsive selections. Elevation, opacity, motion, the complete ANSI 16-color terminal palette, provenance, SPDX licensing, fallback, and version policy are required domains.

The fixed product thresholds are narrow through 719 px, regular through 1199 px, and wide from 1200 px; themes cannot redefine them. Compatibility is exactly N/N-1. The built-in default does not depend on storage or a service, a missing token fails, last-known-good identity is a semantic hash contract, and unknown required versions fail closed.

No external asset packs are accepted in the first release. Semantic assets are package-relative and bounded to 64 IDs, 512 KiB decoded each, and 4 MiB decoded total. Source, compiled pack, catalog, token, alias, depth, nesting, string, and runtime snapshot limits are machine-readable in the schema.

This contract does not authorize runtime import, arbitrary commands, scripts, templates, hooks, user-managed themes, hot activation, services, persistence, FIDL, Product Assembly, or live-system mutation.
