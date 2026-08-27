from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, Table, TableStyle

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
PLN_LOGO_PATH = ASSETS_DIR / "logo_pln.png"

TEMPLATE_ID = "LGP-20KV-02"
TEMPLATE_VERSION = "2.0"
PAGE_SIZE = landscape(A4)

AlignmentType = Literal[0, 1, 2, 4, "left", "center", "centre", "right", "justify"]

# Corporate-neutral palette with PLN-inspired accent.
NAVY = colors.HexColor("#005B71")
NAVY_2 = colors.HexColor("#086A83")
PLN_BLUE = colors.HexColor("#00A2D9")
PLN_CYAN = colors.HexColor("#00A9C9")
PLN_YELLOW = colors.HexColor("#FFF000")
TEXT = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#667085")
GRID = colors.HexColor("#D0D7E2")
SOFT = colors.HexColor("#F5F8FB")
SOFT_BLUE = colors.HexColor("#EAF5FA")
WHITE = colors.white
TOTAL_BG = colors.HexColor("#EEF5F8")
SUCCESS = colors.HexColor("#087A55")

MONTHS_ID: dict[int, str] = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember",
}


def safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return default
    return text


def format_datetime_wib(value: Any) -> str:
    text = safe_text(value)
    if not text:
        return "-"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone(timedelta(hours=7)))
        return f"{dt.day:02d} {MONTHS_ID[dt.month]} {dt.year} - {dt:%H:%M} WIB"
    except Exception:
        return text


def format_date_wib(value: Any) -> str:
    text = safe_text(value)
    if not text:
        return "-"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone(timedelta(hours=7)))
        return f"{dt.day:02d} {MONTHS_ID[dt.month]} {dt.year}"
    except Exception:
        return text


def build_document_id(*, report_year: int, report_month: int, gi_flc: str, monthly_report_id: str) -> str:
    gi_code = safe_text(gi_flc, "GI").replace(" ", "").replace("/", "-")
    short_id = safe_text(monthly_report_id, "00000000")[:8].upper()
    return f"MREP-{report_year}-{report_month:02d}-{gi_code}-{short_id}"


def _logo() -> Any:
    if PLN_LOGO_PATH.exists():
        try:
            return Image(str(PLN_LOGO_PATH), width=13 * mm, height=13 * mm)
        except Exception:
            pass
    styles = getSampleStyleSheet()
    return Paragraph(
        "<b>PLN</b>",
        ParagraphStyle(
            "logo_fallback", parent=styles["Normal"], fontName="Helvetica-Bold",
            fontSize=10, textColor=PLN_BLUE, alignment=TA_CENTER,
        ),
    )


def _p(text: str, *, size: float = 7, bold: bool = False, color: Any = TEXT,
       align: AlignmentType = TA_LEFT, leading: float | None = None) -> Paragraph:
    styles = getSampleStyleSheet()
    return Paragraph(
        text,
        ParagraphStyle(
            f"p_{size}_{bold}_{align}_{id(text)}",
            parent=styles["Normal"],
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size,
            leading=leading or size * 1.22,
            textColor=color,
            alignment=align,
        ),
    )


def build_modern_header(
    *,
    gi_name: str,
    report_title: str,
    period_text: str,
    document_id: str,
) -> Table:
    org = Table(
        [[
            _logo(),
            _p(
                "<b>PT PLN (PERSERO)</b><br/>"
                "UIP3B SUMATERA<br/>"
                "UPT PEMATANG SIANTAR<br/>"
                f"<b>{safe_text(gi_name).upper()}</b>",
                size=6.7,
                color=WHITE,
                leading=8.1,
            ),
        ]],
        colWidths=[17 * mm, 58 * mm],
    )

    org.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    title = _p(
        f"<b>{report_title}</b><br/>"
        f"<font color='#DCEEF3' size='8'>{period_text.upper()}</font>",
        size=10.6,
        bold=True,
        color=WHITE,
        align=TA_CENTER,
        leading=12.6,
    )

    meta = Table(
        [
            [
                _p(
                    "DOKUMEN MANUAL",
                    size=5.5,
                    bold=True,
                    color=WHITE,
                    align=TA_RIGHT,
                )
            ],
            [
                _p(
                    "SISTEM MANAJEMEN TERINTEGRASI",
                    size=5.3,
                    bold=True,
                    color=colors.HexColor("#D8EEF3"),
                    align=TA_RIGHT,
                )
            ],
            [
                _p(
                    "DOCUMENT ID",
                    size=5.1,
                    bold=True,
                    color=colors.HexColor("#D8EEF3"),
                    align=TA_RIGHT,
                )
            ],
            [
                _p(
                    document_id,
                    size=6.0,
                    bold=True,
                    color=WHITE,
                    align=TA_RIGHT,
                )
            ],
            [
                _p(
                    f"{TEMPLATE_ID}  |  Rev. {TEMPLATE_VERSION}",
                    size=5.3,
                    color=colors.HexColor("#D8EEF3"),
                    align=TA_RIGHT,
                )
            ],
        ],
        colWidths=[73 * mm],
    )

    meta.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY_2),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0.75 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.75 * mm),
            ]
        )
    )

    header = Table(
        [[org, title, meta]],
        colWidths=[77 * mm, 128 * mm, 76 * mm],
        rowHeights=[24 * mm],
    )

    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), NAVY),
                ("BACKGROUND", (1, 0), (1, 0), NAVY),
                ("BACKGROUND", (2, 0), (2, 0), NAVY_2),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 3 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 2 * mm),
                ("LEFTPADDING", (1, 0), (1, 0), 2 * mm),
                ("RIGHTPADDING", (1, 0), (1, 0), 2 * mm),
                ("LEFTPADDING", (2, 0), (2, 0), 0),
                ("RIGHTPADDING", (2, 0), (2, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, 0), 1.8, PLN_YELLOW),
            ]
        )
    )

    return header



def build_kpi_strip(items: list[tuple[str, str]]) -> Table:
    cells: list[Any] = []
    for label, value in items:
        card = Table(
            [[
                _p(label.upper(), size=5.4, bold=True, color=MUTED),
                _p(value, size=9.2, bold=True, color=NAVY, align=TA_RIGHT),
            ]],
            colWidths=[28 * mm, 31 * mm],
        )
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SOFT),
            ("BOX", (0, 0), (-1, -1), 0.35, GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1.7 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7 * mm),
        ]))
        cells.append(card)

    strip = Table([cells], colWidths=[61 * mm] * len(cells))
    strip.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return strip


def make_qr(payload: str, *, size_mm: float = 14.5) -> Drawing:
    qr = QrCodeWidget(payload)
    x1, y1, x2, y2 = qr.getBounds()
    width = x2 - x1
    height = y2 - y1
    size = size_mm * mm
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(qr)
    return drawing


def draw_modern_page_decor(
    canvas: Any,
    document: Any,
    *,
    report: dict[str, Any],
    gi_name: str,
    gi_flc: str,
    report_year: int,
    report_month: int,
) -> None:
    page_width, page_height = PAGE_SIZE
    monthly_report_id = safe_text(report.get("monthly_report_id"), "-")
    document_id = build_document_id(
        report_year=report_year,
        report_month=report_month,
        gi_flc=gi_flc,
        monthly_report_id=monthly_report_id,
    )
    signer_name = safe_text(report.get("signer_name"), "-")
    signer_position = safe_text(report.get("signer_position"), "-")
    role = safe_text(report.get("verified_role"), "-")
    verified_at = format_datetime_wib(report.get("verified_at"))
    verified_date = format_date_wib(report.get("verified_at"))
    signature_token = safe_text(report.get("signature_token"), "-")

    canvas.saveState()

    # Minimal modern top accent.
    canvas.setFillColor(NAVY)
    canvas.rect(6 * mm, page_height - 7.4 * mm, page_width - 12 * mm, 1.6 * mm, fill=1, stroke=0)
    canvas.setFillColor(PLN_CYAN)
    canvas.rect(6 * mm, page_height - 7.4 * mm, 42 * mm, 1.6 * mm, fill=1, stroke=0)
    canvas.setFillColor(PLN_YELLOW)
    canvas.rect(6 * mm, page_height - 8.1 * mm, page_width - 12 * mm, 0.45 * mm, fill=1, stroke=0)

    # Bottom divider.
    footer_y = 18.5 * mm
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.45)
    canvas.line(7 * mm, footer_y + 13.5 * mm, page_width - 7 * mm, footer_y + 13.5 * mm)

    # Left footer metadata.
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica-Bold", 5.6)
    canvas.drawString(8 * mm, footer_y + 9 * mm, "VERIFIED DOCUMENT")
    canvas.setFont("Helvetica", 5.5)
    canvas.drawString(8 * mm, footer_y + 5.6 * mm, f"{document_id}  |  {TEMPLATE_ID} Rev. {TEMPLATE_VERSION}")
    canvas.drawString(8 * mm, footer_y + 2.5 * mm, "Generated automatically by Laporan Gangguan Penyulang")

    # Center status chip.
    chip_x = 126 * mm
    chip_y = footer_y + 3 * mm
    canvas.setFillColor(colors.HexColor("#E9F7F1"))
    canvas.roundRect(chip_x, chip_y, 36 * mm, 8 * mm, 2 * mm, fill=1, stroke=0)
    canvas.setFillColor(SUCCESS)
    canvas.setFont("Helvetica-Bold", 6.3)
    canvas.drawCentredString(chip_x + 18 * mm, chip_y + 2.8 * mm, "TERVERIFIKASI")

    # Right e-sign card.
    card_x = page_width - 101 * mm
    card_y = 7.8 * mm
    card_w = 93 * mm
    card_h = 23 * mm
    canvas.setFillColor(SOFT)
    canvas.setStrokeColor(GRID)
    canvas.roundRect(card_x, card_y, card_w, card_h, 2 * mm, fill=1, stroke=1)

    qr_payload = (
        f"document_id={document_id}|report_id={monthly_report_id}|gi={gi_name}|"
        f"period={report_year}-{report_month:02d}|signer={signer_name}|role={role}|"
        f"verified_at={verified_at}|signature={signature_token}"
    )
    qr = make_qr(qr_payload, size_mm=14.2)
    renderPDF.draw(qr, canvas, card_x + 4 * mm, card_y + 4.2 * mm)

    text_x = card_x + 23 * mm
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 6.2)
    canvas.drawString(text_x, card_y + 17.2 * mm, "E-SIGN VERIFIED")
    canvas.setFillColor(TEXT)
    canvas.setFont("Helvetica-Bold", 6.4)
    canvas.drawString(text_x, card_y + 13.6 * mm, signer_name[:38])
    canvas.setFont("Helvetica", 5.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(text_x, card_y + 10.4 * mm, f"{signer_position[:32]}  |  {role}")
    canvas.drawString(text_x, card_y + 7.3 * mm, verified_at)
    canvas.drawString(text_x, card_y + 4.2 * mm, f"Signature: {signature_token[:18]}...")

    canvas.setFont("Helvetica", 5.4)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(page_width - 8 * mm, footer_y + 9.2 * mm, f"{safe_text(gi_name)}, {verified_date}")

    canvas.restoreState()