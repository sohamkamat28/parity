# Third-party components

Dependency versions are recorded in requirements-lock.txt and frontend/package-lock.json. Dependencies retain their respective licenses. This archive does not contain the Python environment, Chromium, llama.cpp binaries, or model weights; setup downloads pinned runtime assets into .cache.

- Inter and JetBrains Mono fonts are bundled with the frontend under the SIL Open Font License 1.1. Full licenses are included in licenses/.
- Local chat: [Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF), pinned repository revision `91cad51170dc346986eccefdc2dd33a9da36ead9`, Q4_K_M file. Apache 2.0 model license.
- Local inference: [llama.cpp](https://github.com/ggml-org/llama.cpp), Windows CPU build b11642. MIT license. Its archive and the model download are SHA-256 checked by scripts/setup_local_chat.py.
- Embeddings: [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), pinned revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Apache 2.0 model license.
- Browser rendering uses Playwright and its matching Chromium distribution. PDF extraction uses PyMuPDF. Python and JavaScript dependencies are installed from their upstream distributions; inspect their included licenses for reuse or redistribution.

The mock college portal contains synthetic demonstration text and generated demonstration PDFs. Public validation used the demonstration website quotes.toscrape.com; its fetched content and databases are not included in this release archive.
