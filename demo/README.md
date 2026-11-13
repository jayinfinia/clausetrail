# Fictional corpus

`fixtures/` contains 12 clearly fictional text agreements, a tracker CSV and expected metadata. The in-app seed loads these cases through the actual ingestion pipeline. `python -m scripts.generate_formats` produces DOCX, text/scanned PDF and XLSX variants plus corrupt/injection fixtures outside git under `.local/format-fixtures`.

All parties and terms are fictional. The corpus demonstrates workflows, not legal validity or production extraction accuracy. Test expectations also include independently asserted date arithmetic, permissions and citations in tests/.
