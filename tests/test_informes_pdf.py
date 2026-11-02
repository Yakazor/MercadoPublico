import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import informes_pdf  # noqa: E402


def test_solo_se_reimprimen_los_pdf_cuyo_contenido_cambio(tmp_path):
    md_a, md_b = tmp_path / "a.md", tmp_path / "b.md"
    md_a.write_text("# A\n\nTexto", encoding="utf-8")
    md_b.write_text("# B\n\nTexto", encoding="utf-8")
    pdf_a, pdf_b = tmp_path / "A.pdf", tmp_path / "B.pdf"
    pares = [(md_a, pdf_a), (md_b, pdf_b)]
    assert len(informes_pdf.pendientes(pares, {})) == 2                    # sin PDF: todos
    pdf_a.write_bytes(b"%PDF"), pdf_b.write_bytes(b"%PDF")
    huellas = {pdf.name: h for _, pdf, _, h in informes_pdf.pendientes(pares, {})}
    assert informes_pdf.pendientes(pares, huellas) == []                    # nada cambió
    md_b.write_text("# B\n\nOtro texto", encoding="utf-8")
    assert [pdf.name for _, pdf, _, _ in informes_pdf.pendientes(pares, huellas)] == ["B.pdf"]
    pdf_a.unlink()
    assert {pdf.name for _, pdf, _, _ in informes_pdf.pendientes(pares, huellas)} == {"A.pdf", "B.pdf"}
