from datetime import datetime
from io import BytesIO

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import (
    getSampleStyleSheet,
    ParagraphStyle,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm

def _build_source_summary_data(source_schema: dict) -> list:
    """
    Build a source summary table that works for both file schemas
    (which have row_count / column_count) and ERP schemas (which don't).
    """
    system = source_schema.get("system", "unknown").upper()
    entity = source_schema.get("model") or source_schema.get("entity", "—")
    label = source_schema.get("name") or source_schema.get("label", entity)
    field_count = source_schema.get("field_count") or len(
        source_schema.get("fields", {})
    )

    rows = [
        ["Source System", system],
        ["Entity", f"{label} ({entity})" if label != entity else entity],
        ["Fields Analyzed", field_count],
    ]

    # CSV/file-specific rows — only add if present
    if "row_count" in source_schema and source_schema["row_count"] is not None:
        rows.insert(2, ["Record Count", source_schema["row_count"]])

    return rows

def build_styles():
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=28,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1E293B"),
        )
    )

    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#1E293B"),
            spaceAfter=8,
        )
    )

    styles.add(
        ParagraphStyle(
            name="Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#374151"),
        )
    )

    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4B5563"),
        )
    )

    return styles


def wrapped(text, style):
    if text is None:
        text = ""
    return Paragraph(str(text), style)


def build_mapping_table(mapping_suggestions, styles):
    header_style = ParagraphStyle(
        "HeaderWhite",
        parent=styles["Small"],
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    data = [
        [
            wrapped("Source Field", header_style),
            wrapped("Target Field", header_style),
            wrapped("Confidence", header_style),
            wrapped("Reason", header_style),
        ]
    ]

    for item in mapping_suggestions:
        data.append([
            wrapped(item.get("source_field"), styles["Body"]),
            wrapped(item.get("target_field"), styles["Body"]),
            wrapped(item.get("confidence"), styles["Body"]),
            wrapped(item.get("reason"), styles["Small"]),
        ])

    table = Table(
        data,
        colWidths=[35 * mm, 35 * mm, 25 * mm, 85 * mm],
        repeatRows=1,
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
            colors.white,
            colors.HexColor("#F9FAFB"),
        ]),
    ]))

    return table


def build_issue_table(issues, styles):
    header_style = ParagraphStyle(
        "HeaderWhite2",
        parent=styles["Small"],
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    data = [
        [
            wrapped("Severity", header_style),
            wrapped("Issue", header_style),
            wrapped("Recommendation", header_style),
        ]
    ]

    for issue in issues:
        data.append([
            wrapped(issue.get("severity", "").upper(), styles["Body"]),
            wrapped(issue.get("issue"), styles["Small"]),
            wrapped(issue.get("recommendation"), styles["Small"]),
        ])

    table = Table(
        data,
        colWidths=[25 * mm, 75 * mm, 85 * mm],
        repeatRows=1,
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
            colors.white,
            colors.HexColor("#F9FAFB"),
        ]),
    ]))

    return table


def generate_report(
    source_profile,
    prediction,
    schema,
    compatibility,
):
    styles = build_styles()

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    story = []

    # Cover
    story.append(
        Paragraph(
            "ERP Migration Compatibility Assessment Report",
            styles["ReportTitle"],
        )
    )

    story.append(Spacer(1, 16))

    story.append(
        Paragraph(
            f"Generated on: {datetime.now().strftime('%d %B %Y, %I:%M %p')}",
            styles["Small"],
        )
    )

    story.append(Spacer(1, 24))

    # Executive summary
    story.append(
        Paragraph(
            "Executive Summary",
            styles["SectionHeading"],
        )
    )

    story.append(
        wrapped(
            compatibility["overall_assessment"],
            styles["Body"],
        )
    )

    story.append(Spacer(1, 20))

    # Dataset summary
    story.append(Paragraph("Source Summary", styles["SectionHeading"]))
    summary_data = _build_source_summary_data(source_profile)

    summary_table = Table(summary_data, colWidths=[60 * mm, 40 * mm])

    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F9FAFB")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(summary_table)
    story.append(Spacer(1, 20))

    # AI prediction
    story.append(
        Paragraph(
            "AI Target Entity Prediction",
            styles["SectionHeading"],
        )
    )

    prediction_data = [
        ["Dataset Type", prediction["dataset_type"]],
        ["Predicted Entity", prediction["predicted_model_name"]],
        ["Technical Entity", prediction["predicted_model"]],
        ["Confidence", str(prediction["confidence"])],
    ]

    prediction_table = Table(
        prediction_data,
        colWidths=[60 * mm, 110 * mm],
    )

    prediction_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F9FAFB")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(prediction_table)
    story.append(Spacer(1, 20))

    # Mappings
    story.append(
        Paragraph(
            "Field Mapping Suggestions",
            styles["SectionHeading"],
        )
    )

    story.append(
        build_mapping_table(
            compatibility["mapping_suggestions"],
            styles,
        )
    )

    story.append(Spacer(1, 20))

    # Issues
    story.append(
        Paragraph(
            "Compatibility Issues",
            styles["SectionHeading"],
        )
    )

    story.append(
        build_issue_table(
            compatibility["compatibility_issues"],
            styles,
        )
    )

    story.append(Spacer(1, 20))

    # Recommendations
    story.append(
        Paragraph(
            "Export Recommendations",
            styles["SectionHeading"],
        )
    )

    for rec in compatibility["export_recommendations"]:
        story.append(
            wrapped(f"- {rec}", styles["Body"])
        )

    story.append(Spacer(1, 20))

    # Schema
    story.append(
        Paragraph(
            "Target Entity Summary",
            styles["SectionHeading"],
        )
    )

    schema_data = [
        ["Target Entity", schema["model"]],
        ["Raw Schema Fields", schema["field_count"]],
    ]

    schema_table = Table(
        schema_data,
        colWidths=[60 * mm, 80 * mm],
    )

    schema_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F9FAFB")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(schema_table)

    doc.build(story)

    return output.getvalue()
 