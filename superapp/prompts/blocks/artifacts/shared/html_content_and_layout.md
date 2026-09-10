## Content and layout
- No filler. Every element earns its place: no placeholder text, no dummy sections, no data slop.
- Static means static. Nothing reaches a server, so do not ship a `Send`/`Save`/`Submit` that only fakes success; use download, copy, or `mailto:` instead. A planner or tracker is filled read-only content, not blank cells or checkboxes that reset on refresh (a form that computes a downloadable result is fine).
- No sideways scroll on mobile, page-level or inside a component: reflow instead (wrap or stack rows; a wide table becomes stacked cards).
- Use images on visual pages, following the image guidance below.
{artifact_image_guidance}
