#!/usr/bin/env python3
"""Generate single-slide PowerPoint snapshots with multiple panels.

Each panel can contain a figure (SVG/PNG) and/or a table (CSV).

Usage:
    python generate_panel_snapshot.py \
        --figures-dir /path/to/KRAS-COADREAD/2026-09-10__2.0.0__23ad0c5/figures \
        --snapshot-config snapshot_dependency.yaml \
        --template /path/to/template.potx \
        --output KRAS-COADREAD-dependency.pptx
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import click
import yaml

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.dml.color import RGBColor
    from pptx.table import Table
except ImportError:
    raise ImportError("python-pptx is required. Install with: pip install python-pptx")

try:
    import cairosvg
    HAS_CAIROSVG = True
except ImportError:
    HAS_CAIROSVG = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


SKILL_DIR = Path(__file__).parent.parent


@dataclass
class TableRowSelect:
    """Row selection by column values."""
    column: str
    values: list[str]


@dataclass
class PanelSpec:
    """A panel containing a figure and/or table."""
    figure: Optional[str] = None
    table: Optional[str] = None
    caption: str = ""
    table_max_rows: int = 10
    table_columns: Optional[list[str]] = None
    table_row_select: Optional[TableRowSelect] = None
    table_filter: Optional[str] = None  # pandas query string
    table_sort_by: Optional[str] = None
    table_sort_ascending: bool = True


@dataclass
class SnapshotSpec:
    """A single-slide snapshot specification."""
    title: str = ""
    subtitle: str = ""
    layout: str = "1x2"  # rows x cols
    panels: list[PanelSpec] = field(default_factory=list)


def load_snapshot_config(config_path: Path) -> SnapshotSpec:
    """Load snapshot configuration from YAML."""
    with config_path.open() as f:
        data = yaml.safe_load(f)

    panels = []
    for panel_cfg in data.get("panels", []):
        # Parse table_row_select if present
        row_select = None
        if "table_row_select" in panel_cfg:
            rs = panel_cfg["table_row_select"]
            row_select = TableRowSelect(
                column=rs.get("column", ""),
                values=rs.get("values", []),
            )

        panels.append(PanelSpec(
            figure=panel_cfg.get("figure"),
            table=panel_cfg.get("table"),
            caption=panel_cfg.get("caption", ""),
            table_max_rows=panel_cfg.get("table_max_rows", 10),
            table_columns=panel_cfg.get("table_columns"),
            table_row_select=row_select,
            table_filter=panel_cfg.get("table_filter"),
            table_sort_by=panel_cfg.get("table_sort_by"),
            table_sort_ascending=panel_cfg.get("table_sort_ascending", True),
        ))

    return SnapshotSpec(
        title=data.get("title", ""),
        subtitle=data.get("subtitle", ""),
        layout=data.get("layout", "1x2"),
        panels=panels,
    )


def parse_figures_dir(figures_dir: Path) -> tuple[str, str]:
    """Extract gene and indication from figures directory path."""
    run_folder_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}__[\d.]+__[a-f0-9]+$")

    current = figures_dir
    if current.name == "figures":
        current = current.parent

    if run_folder_pattern.match(current.name):
        parent = current.parent.name
        match = re.match(r"^([A-Z0-9]+)-([A-Z]+)$", parent, re.IGNORECASE)
        if match:
            return match.group(1).upper(), match.group(2).upper()

    for part in reversed(current.parts):
        if part.startswith("OneDrive") or part.startswith("."):
            continue
        match = re.match(r"^([A-Z0-9]+)-([A-Z]+)$", part, re.IGNORECASE)
        if match and len(match.group(1)) <= 10 and len(match.group(2)) <= 10:
            return match.group(1).upper(), match.group(2).upper()

    raise ValueError(f"Could not parse gene-indication from path: {figures_dir}")


def substitute_placeholders(text: str, gene: str, indication: str) -> str:
    """Replace placeholders in text with actual values."""
    return text.replace("{gene}", gene).replace("{indication}", indication)


def parse_layout(layout: str) -> tuple[int, int]:
    """Parse layout string like '2x2' into (rows, cols)."""
    match = re.match(r"(\d+)x(\d+)", layout)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1, 2  # default


def svg_to_png(svg_path: Path, scale: float = 2.0) -> bytes:
    """Convert SVG to PNG bytes using cairosvg."""
    if not HAS_CAIROSVG:
        raise ImportError("cairosvg is required for SVG conversion.")
    return cairosvg.svg2png(url=str(svg_path), scale=scale)


def get_image_bytes(figure_path: Path) -> tuple[bytes, str]:
    """Get image bytes and format, converting SVG if needed."""
    suffix = figure_path.suffix.lower()
    if suffix == ".svg":
        return svg_to_png(figure_path), "png"
    elif suffix == ".png":
        return figure_path.read_bytes(), "png"
    elif suffix in (".jpg", ".jpeg"):
        return figure_path.read_bytes(), "jpeg"
    else:
        raise ValueError(f"Unsupported image format: {suffix}")


def load_table_data(
    table_path: Path,
    max_rows: int = 10,
    columns: Optional[list[str]] = None,
    row_select: Optional[TableRowSelect] = None,
    filter_query: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_ascending: bool = True,
) -> tuple[list[str], list[list[str]]]:
    """Load table data from CSV or Parquet with filtering, sorting, and row selection."""
    import pandas as pd

    suffix = table_path.suffix.lower()

    # Load data into pandas DataFrame
    if suffix == ".parquet":
        df = pd.read_parquet(table_path)
    elif suffix == ".csv":
        df = pd.read_csv(table_path)
    else:
        raise ValueError(f"Unsupported table format: {suffix}")

    # Apply row selection by column values
    if row_select and row_select.column and row_select.values:
        if row_select.column in df.columns:
            df = df[df[row_select.column].isin(row_select.values)]

    # Apply pandas query filter
    if filter_query:
        df = df.query(filter_query)

    # Apply sorting
    if sort_by and sort_by in df.columns:
        df = df.sort_values(by=sort_by, ascending=sort_ascending)

    # Select columns
    if columns:
        available_cols = [c for c in columns if c in df.columns]
        df = df[available_cols]

    # Limit rows
    df = df.head(max_rows)

    # Format output
    headers = list(df.columns)
    rows = []
    for _, row in df.iterrows():
        formatted_row = []
        for val in row:
            if isinstance(val, float):
                formatted_row.append(f"{val:.3f}")
            elif isinstance(val, bool):
                formatted_row.append("Yes" if val else "No")
            else:
                formatted_row.append(str(val))
        rows.append(formatted_row)

    return headers, rows


def add_table_to_slide(slide, table_data: tuple[list[str], list[list[str]]],
                       left: int, top: int, width: int, height: int) -> None:
    """Add a table to the slide."""
    headers, rows = table_data
    if not headers:
        return

    n_rows = len(rows) + 1  # +1 for header
    n_cols = len(headers)

    col_width = width // n_cols
    row_height = min(height // n_rows, Inches(0.3))

    table_shape = slide.shapes.add_table(n_rows, n_cols, left, top, width, int(row_height * n_rows))
    table = table_shape.table

    # Style header row
    for j, header in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = str(header)
        cell.text_frame.paragraphs[0].font.size = Pt(8)
        cell.text_frame.paragraphs[0].font.bold = True
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(0, 51, 102)
        cell.text_frame.paragraphs[0].font.color.rgb = RGBColor(255, 255, 255)

    # Data rows
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            cell = table.cell(i + 1, j)
            cell.text = str(value)
            cell.text_frame.paragraphs[0].font.size = Pt(7)


def load_presentation_from_template(template_path: Path) -> Presentation:
    """Load a presentation from template, handling both .pptx and .potx files."""
    suffix = template_path.suffix.lower()

    if suffix == ".potx":
        temp_dir = tempfile.mkdtemp()
        temp_pptx = Path(temp_dir) / "presentation.pptx"

        with zipfile.ZipFile(template_path, 'r') as zf_in:
            with zipfile.ZipFile(temp_pptx, 'w', zipfile.ZIP_DEFLATED) as zf_out:
                for item in zf_in.infolist():
                    data = zf_in.read(item.filename)
                    if item.filename == '[Content_Types].xml':
                        data = data.decode('utf-8').replace(
                            'application/vnd.openxmlformats-officedocument.presentationml.template.main+xml',
                            'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'
                        ).encode('utf-8')
                    zf_out.writestr(item, data)

        prs = Presentation(str(temp_pptx))
        shutil.rmtree(temp_dir, ignore_errors=True)
        return prs

    return Presentation(str(template_path))


def generate_panel_snapshot(
    figures_dir: Path,
    snapshot_config: SnapshotSpec,
    template_path: Path,
    output_path: Path,
) -> None:
    """Generate a single-slide snapshot with multiple panels."""
    gene, indication = parse_figures_dir(figures_dir)
    click.echo(f"Generating panel snapshot for {gene} in {indication}")

    prs = load_presentation_from_template(template_path)

    # Use layout 8 for content slide
    slide_layout = prs.slide_layouts[8]
    slide = prs.slides.add_slide(slide_layout)

    slide_width = prs.slide_width
    slide_height = prs.slide_height

    # Add title
    title_text = substitute_placeholders(snapshot_config.title, gene, indication)
    title_box = slide.shapes.add_textbox(
        Inches(0.5), Inches(0.3), slide_width - Inches(1), Inches(0.5)
    )
    title_frame = title_box.text_frame
    title_para = title_frame.paragraphs[0]
    title_para.text = title_text
    title_para.font.size = Pt(24)
    title_para.font.bold = True
    title_para.font.color.rgb = RGBColor(0, 51, 102)

    # Add subtitle if present
    content_top = Inches(0.8)
    if snapshot_config.subtitle:
        subtitle_text = substitute_placeholders(snapshot_config.subtitle, gene, indication)
        subtitle_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(0.75), slide_width - Inches(1), Inches(0.3)
        )
        subtitle_frame = subtitle_box.text_frame
        subtitle_para = subtitle_frame.paragraphs[0]
        subtitle_para.text = subtitle_text
        subtitle_para.font.size = Pt(14)
        subtitle_para.font.color.rgb = RGBColor(102, 102, 102)
        content_top = Inches(1.1)

    # Parse layout
    rows, cols = parse_layout(snapshot_config.layout)

    # Calculate panel dimensions
    margin = Inches(0.3)
    panel_gap = Inches(0.2)

    content_width = slide_width - (2 * margin)
    content_height = slide_height - content_top - margin

    panel_width = (content_width - (cols - 1) * panel_gap) / cols
    panel_height = (content_height - (rows - 1) * panel_gap) / rows

    # Add panels
    for idx, panel in enumerate(snapshot_config.panels):
        if idx >= rows * cols:
            click.echo(f"  Warning: Too many panels for {rows}x{cols} layout, skipping panel {idx+1}", err=True)
            break

        row = idx // cols
        col = idx % cols

        panel_left = margin + col * (panel_width + panel_gap)
        panel_top = content_top + row * (panel_height + panel_gap)

        # Determine space allocation for figure vs table
        has_figure = panel.figure is not None
        has_table = panel.table is not None

        if has_figure and has_table:
            figure_height = panel_height * 0.6
            table_height = panel_height * 0.35
        elif has_figure:
            figure_height = panel_height * 0.85
            table_height = 0
        else:
            figure_height = 0
            table_height = panel_height * 0.85

        current_top = panel_top

        # Add figure
        if panel.figure:
            fig_path = figures_dir / panel.figure
            if not fig_path.exists():
                # Try without 'figures/' prefix
                fig_path = figures_dir.parent / "figures" / panel.figure

            if fig_path.exists():
                try:
                    img_bytes, img_format = get_image_bytes(fig_path)
                    img_stream = io.BytesIO(img_bytes)

                    if HAS_PIL:
                        with Image.open(io.BytesIO(img_bytes)) as img:
                            img_w, img_h = img.size
                        aspect = img_w / img_h
                    else:
                        aspect = 1.5

                    # Fit figure within allocated space
                    if panel_width / figure_height > aspect:
                        actual_height = figure_height
                        actual_width = figure_height * aspect
                    else:
                        actual_width = panel_width
                        actual_height = panel_width / aspect

                    # Center the figure
                    fig_left = panel_left + (panel_width - actual_width) / 2

                    slide.shapes.add_picture(img_stream, int(fig_left), int(current_top),
                                            width=int(actual_width), height=int(actual_height))
                    current_top += actual_height + Inches(0.1)

                except Exception as e:
                    click.echo(f"  Warning: Could not add figure {panel.figure}: {e}", err=True)
            else:
                click.echo(f"  Warning: Figure not found: {panel.figure}", err=True)

        # Add table
        if panel.table:
            table_path = figures_dir / panel.table
            if not table_path.exists():
                # Try in parent's tables directory
                table_path = figures_dir.parent / "tables" / panel.table
            if not table_path.exists():
                # Try relative to figures dir
                table_path = figures_dir.parent / panel.table

            if table_path.exists():
                try:
                    table_data = load_table_data(
                        table_path,
                        max_rows=panel.table_max_rows,
                        columns=panel.table_columns,
                        row_select=panel.table_row_select,
                        filter_query=panel.table_filter,
                        sort_by=panel.table_sort_by,
                        sort_ascending=panel.table_sort_ascending,
                    )
                    if table_data[0]:  # has headers
                        add_table_to_slide(slide, table_data,
                                          int(panel_left), int(current_top),
                                          int(panel_width), int(table_height))
                        current_top += table_height + Inches(0.05)
                except Exception as e:
                    click.echo(f"  Warning: Could not add table {panel.table}: {e}", err=True)
            else:
                click.echo(f"  Warning: Table not found: {panel.table}", err=True)

        # Add caption
        if panel.caption:
            caption_box = slide.shapes.add_textbox(
                int(panel_left), int(current_top), int(panel_width), Inches(0.25)
            )
            caption_frame = caption_box.text_frame
            caption_para = caption_frame.paragraphs[0]
            caption_para.text = panel.caption
            caption_para.font.size = Pt(9)
            caption_para.font.color.rgb = RGBColor(102, 102, 102)
            caption_para.alignment = PP_ALIGN.CENTER

    prs.save(str(output_path))
    click.echo(f"  Saved: {output_path}")


@click.command()
@click.option(
    "--figures-dir", "-f",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to figures directory (e.g., .../KRAS-COADREAD/.../figures)",
)
@click.option(
    "--snapshot-config", "-c",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to snapshot configuration YAML",
)
@click.option(
    "--template", "-t",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to PowerPoint template (.potx or .pptx)",
)
@click.option(
    "--output", "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output PPTX path (default: {gene}-{indication}-snapshot.pptx)",
)
def main(
    figures_dir: Path,
    snapshot_config: Path,
    template: Path,
    output: Optional[Path],
) -> None:
    """Generate a single-slide snapshot with multiple panels."""
    config = load_snapshot_config(snapshot_config)

    if output is None:
        try:
            gene, indication = parse_figures_dir(figures_dir)
            output = Path(f"{gene}-{indication}-panel-snapshot.pptx")
        except ValueError:
            output = Path("panel-snapshot.pptx")

    generate_panel_snapshot(
        figures_dir=figures_dir,
        snapshot_config=config,
        template_path=template,
        output_path=output,
    )


if __name__ == "__main__":
    main()
