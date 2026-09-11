# V2 PDF pagination and contents plan

## Goal
Eliminate clipped content in the fixed-A4 V2 report, add a premium-feeling table of contents with stable page references, fix malformed multi-placeholder markup, and make future layout regressions visible during rendering.

## Findings
The current `.page` uses a fixed A4 `height` plus `overflow: hidden`, so content beyond the content area is silently cut off. The V2 sample has confirmed overflow in the radar/evidence page (+102px), keyword matrix (+190px), Appendix A (+347px), a STAR page (+39px), and the Career tail page (+113px). The existing table-of-contents CSS is legacy-only; no contents page is emitted.

## Changes

### 1. `templates/report.html`: deterministic section pagination and contents

1. Define template-level pagination values before report output:
   - top prescription count;
   - radar visual page plus evidence-table page(s);
   - keyword-matrix chunks with a conservative row budget;
   - interview-preparation chunks;
   - seven-day-plan chunks;
   - appendix weakness pages (one card per page);
   - STAR example page counts;
   - Career tail-page count.
2. Add a dedicated **Contents / 报告目录** page immediately after the cover. It will list the primary chapters and appendices, show computed printed-page numbers, and use continuation labels only where a chapter spans pages. This keeps the directory useful in the PDF rather than being decorative.
3. Rebuild the radar chapter into two page-safe pieces:
   - first page: radar visual and concise score framing;
   - following page: six-dimension evidence/action table, chunked if needed.
4. Chunk the keyword evidence matrix into multiple pages rather than placing all entries in one table. The first page keeps the explanatory copy; later pages receive an explicit “续” label.
5. Render one Appendix A weakness card per page by default. This removes the unreliable two-card assumption for long evidence, rewrite, verification, and completion-standard fields.
6. Make Appendix B robust for verbose STAR data by separating the long STAR narrative from its supporting verification/interview material when the content needs a continuation page. Preserve the copy-ready rewrite rather than shrinking it to illegibility.
7. Simplify the end page’s vertical composition: retain the three Career services, but use smaller card spacing/padding and a compact scope/privacy band so all footer content stays inside the safe region.
8. Replace the unsafe one-time placeholder replacement chain for `[待确认: ...]` with safe plain-text rendering (`white-space: pre-line`) until a proper full-range formatter is introduced. This prevents malformed nested `<span>` markup when a paragraph contains multiple placeholders.

### 2. `templates/styles.css`: page-safe visual refinements

1. Preserve the A4 fixed-page model and header/footer safe zone; do not use `overflow: hidden` as the solution.
2. Add dedicated V2 styles for the contents page and continuation headings.
3. Reduce radar-only visual height and tighten non-essential spacing while retaining current typography hierarchy.
4. Add stable styles for table-page continuations, single-card appendix pages, STAR support/continuation blocks, multiline text, and compact end-page legal/footer content.
5. Use explicit max-width/line-height/padding rules for dynamic tables and cards so dense data remains readable before pagination is triggered.

### 3. `scripts/render.py`: fail-visible layout validation

1. After writing/opening the rendered debug HTML in Playwright, measure every `.page` element’s scroll height versus client height.
2. Emit a report containing page sequence, detected title/label, and overflow pixels.
3. Return a non-zero failure (or an explicit renderer error) when any page overflows so a clipped paid PDF cannot be silently shipped.
4. Keep the debug HTML generation and existing PDF settings intact; only add validation around the existing browser render.

### 4. Regenerate and verify V2 artifacts

1. Render `output/zhaotianyu_diagnosis_v2.json` using the updated template.
2. Confirm the debug HTML and PDF are regenerated at their existing V2 output paths.
3. Run the renderer’s layout validator and verify every `.page` reports `0px` overflow.
4. Visually inspect the contents page, all formerly overflowing chapters, first/last pages of continuation sections, and the final Career page.

## Success criteria

- The PDF includes a polished contents page after the cover with correct printed-page references.
- No `.page` has vertical overflow; no paid-report content is clipped by fixed-height pages.
- Long dynamic report arrays can extend to continuation pages without manual data editing.
- Multiple `[待确认: ...]` placeholders render as readable text without broken HTML.
- The report keeps the V2 premium visual system and all three approved Career follow-up services.
