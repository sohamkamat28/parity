# Parity — presentation walkthrough

Launch Parity, then open **Demo Lab**. Create a fresh demo named for your presentation. Each demo has separate portal state and two sources: Campus and Live Lab. Keep automatic polling paused while walking through the numbered steps.

1. **Establish a baseline.** Run step 01 and wait for `succeeded`. The observed result should be three created documents. In Ask Parity, select this demo's **Campus** source and ask “What is the honours registration deadline?” The answer cites **20 August 2026 at 5:00 PM**. Click the numbered citation to open v1.
2. **Change the deadline.** Run step 02. It changes the actual portal to **28 August 2026 at 5:00 PM** and adds a signed **Head of Department NOC**. One document should be modified. In the same conversation ask “What is the deadline now, and which new document is required?” The answer should quote both current passages with citations.
3. **Travel back.** Open honours history, choose Compare versions, and select v1 → v2. Expect **4 added lines and 1 removed line**, including the NOC heading and paragraph. In Ask Parity choose Historical snapshot and a time between v1 and v2 observations. Ask the original deadline question; it should cite v1. All times in the interface use your computer's local timezone.
4. **Ignore noise.** Run step 03. The portal footer changes, but there should be **zero modified documents and zero new vectors**.
5. **Publish and revise a PDF.** Step 04 publishes an HTML notice plus its PDF: two created documents. Step 05 revises the PDF deadline from **4 October to 7 October 2026**. Inspect its two versions and search for “reassessment application deadline”.
6. **Prove JavaScript rendering.** Step 06 indexes two Live Lab pages. Step 07 changes only the JSON response; the HTML shell stays identical. Select this demo's **Live Lab** source in Ask Parity or Evidence search. “Innovation lab application deadline” should find **25 November**, replacing **18 November** in v2.
7. **Show a disappearance and return.** Step 08 removes the scholarship. It immediately leaves current search, while history remains. Wait at least two seconds before step 09 and another two seconds before step 10. The third independent missing observation confirms deletion. Step 11 restores it. Open Availability & history to see the gap. Historical search during that gap must not return the scholarship.
8. **Simulate an outage.** Step 12 returns HTTP 503 for honours. The run is partial, prior evidence remains searchable with a warning, and its successful verification timestamp stays unchanged. Step 13 clears the fault and crawls again.
9. **Let the schedule work.** Create a second fresh demo and run its baseline. Enable scheduled polling, then click Change without crawling. Within roughly 15 seconds the worker should discover the new honours deadline. Pause scheduling when finished. This second demo leaves the first demo's history intact.
10. **Finish with proof.** In Diagnostics, test the answer model and run all five MCP tools. The tests execute actual requests and display measured milliseconds. Mission Control reflects the real database totals.

Use **Ctrl+K** for the command palette, **Alt+1…6** to switch screens, and **Ctrl+Enter** to send a question. The expand icon enters presentation mode. The activity icon toggles reduced motion; the operating system's reduced-motion preference is also respected. Escape closes dialogs and mobile navigation.

The local model quotes exact selected passages. It is intentionally conservative: it can report insufficient evidence or select an imperfect passage, so inspect citations. Evidence search remains available if the answer model is stopped. To repeat the whole presentation, create another fresh demo instead of resetting or deleting earlier source records.

All college notices, deadlines, payments, and requirements in the portal are synthetic demonstration data.
