# WordPress Hub — companion bridge plugin

**One** WordPress plugin lives under `bridge/imperal-bridge/`: **Imperal
Bridge**. It is the single companion plugin for this connector — it used to
ship as three separate plugins (Imperal SEO Bridge, Imperal Builder Bridge,
Imperal Media Bridge); those are now merged into one file, one version
number, one install step.

**There will not be a fourth bridge plugin.** Every new bridge capability
this connector needs in the future is added to `imperal-bridge/imperal-bridge.php`
as a new section, never as a new plugin.

See `imperal-bridge/README.md` for what it exposes, why it's needed, and how
to install it. The prebuilt zip is `bridge/imperal-bridge.zip` — also
downloadable straight from the WordPress Hub sidebar in the Imperal panel
(secondary button at the bottom of the sidebar).

## Why a bridge is needed at all

WordPress core only exposes post meta over the REST API when it is
registered with `show_in_rest`. Rank Math never does that for its
`rank_math_*` keys (verified against `seo-by-rank-math` 1.0.274.1) and marks
them protected on top of that; neither Elementor nor Bricks do it for their
page-builder trees; and WordPress has no built-in REST endpoint for sideloading
an external image URL into the media library. No Application Password can
work around any of that — a companion plugin running inside WordPress, with
real capability checks, is the only fix.
