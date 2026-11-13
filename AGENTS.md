# Contributor and agent guidance

Read README.md, docs/ARCHITECTURE.md, docs/EVALUATION.md and SECURITY.md before changing code.

- Use fictional data only. Never commit secrets, real agreements or content-bearing logs. `.gitignore` blocks PDF, Word and Excel files; generated formats live in `.local/`.
- Preserve source and version evidence and the reviewer approval boundary: automated values are proposals until a reviewer approves them with a supporting passage.
- Reject unauthorized access in backend code before retrieval, and recheck after inference.
- Do not enable external processing just by changing an environment variable. Destinations must be fixed and enforced in code.
- Add behavior tests for dates, permissions, extraction evidence, cleanup and failure recovery. Run `python -m unittest discover -s tests -v`.
- Changes to retrieval or answer checks must be measured: tune on `--split dev`, then report the CUAD test split in docs/EVALUATION.md.
- Label fixtures, stubs and unimplemented capabilities clearly. Never describe a mock-tested adapter as a working integration.
