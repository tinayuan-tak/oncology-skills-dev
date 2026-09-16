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
    title: str = ""  # Panel title (displayed above content)
    caption: str = ""  # Panel caption (displayed below content)
    table_max_rows: int = 10
    table_columns: Optional[list[str]] = None
    table_row_select: Optional[TableRowSelect] = None
    table_filter: Optional[str] = None  # pandas query string
    table_sort_by: Optional[str] = None
    table_sort_ascending: bool = True


@dataclass
class GroupSpec:
    """A group of panels displayed as a column."""
    title: str = ""
    panels: list[PanelSpec] = field(default_factory=list)


@dataclass
class SnapshotSpec:
    """A single-slide snapshot specification."""
    title: str = ""
    subtitle: str = ""
    layout: str = "1x2"  # rows x cols, or "grouped" for column groups
    panels: list[PanelSpec] = field(default_factory=list)
    groups: list[GroupSpec] = field(default_factory=list)  # For grouped layout


def _parse_panel(panel_cfg: dict) -> PanelSpec:
    """Parse a single panel configuration."""
    row_select = None
    if "table_row_select" in panel_cfg:
        rs = panel_cfg["table_row_select"]
        row_select = TableRowSelect(
            column=rs.get("column", ""),
            values=rs.get("values", []),
        )

    return PanelSpec(
        figure=panel_cfg.get("figure"),
        table=panel_cfg.get("table"),
        title=panel_cfg.get("title", ""),
        caption=panel_cfg.get("caption", ""),
        table_max_rows=panel_cfg.get("table_max_rows", 10),
        table_columns=panel_cfg.get("table_columns"),
        table_row_select=row_select,
        table_filter=panel_cfg.get("table_filter"),
        table_sort_by=panel_cfg.get("table_sort_by"),
        table_sort_ascending=panel_cfg.get("table_sort_ascending", True),
    )


def load_snapshot_config(config_path: Path) -> SnapshotSpec:
    """Load snapshot configuration from YAML."""
    with config_path.open() as f:
        data = yaml.safe_load(f)

    # Parse flat panels
    panels = [_parse_panel(p) for p in data.get("panels", [])]

    # Parse grouped panels
    groups = []
    for group_cfg in data.get("groups", []):
        group_panels = [_parse_panel(p) for p in group_cfg.get("panels", [])]
        groups.append(GroupSpec(
            title=group_cfg.get("title", ""),
            panels=group_panels,
        ))

    return SnapshotSpec(
        title=data.get("title", ""),
        subtitle=data.get("subtitle", ""),
        layout=data.get("layout", "1x2"),
        panels=panels,
        groups=groups,
    )


def parse_run_dir(run_dir: Path) -> tuple[str, str]:
    """Extract gene and indication from run directory path.

    Expected path: .../target-profile/{GENE}-{INDICATION}/{date}__{version}__{hash}
    """
    run_folder_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}__[\d.]+__[a-f0-9]+$")

    current = run_dir
    # If pointing to figures/ subdirectory, go up
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

    raise ValueError(f"Could not parse gene-indication from path: {run_dir}")


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
    import numpy as np

    def format_value(val):
        """Format a value for display, rounding numbers to 3 significant digits."""
        # Handle None/NaN
        if pd.isna(val):
            return ""

        # Handle booleans (before numeric check, since bool is subclass of int)
        if isinstance(val, (bool, np.bool_)):
            return "Yes" if val else "No"

        # Handle numeric types (including numpy types)
        if isinstance(val, (int, float, np.integer, np.floating)):
            num = float(val)
            if num == 0:
                return "0"
            elif abs(num) >= 1000 or abs(num) < 0.001:
                return f"{num:.2e}"
            else:
                return f"{num:.3g}"

        # Try to parse string as number
        if isinstance(val, str):
            val_stripped = val.strip()
            try:
                num = float(val_stripped)
                if num == 0:
                    return "0"
                elif abs(num) >= 1000 or abs(num) < 0.001:
                    return f"{num:.2e}"
                else:
                    return f"{num:.3g}"
            except (ValueError, TypeError):
                pass

        return str(val)

    headers = list(df.columns)
    rows = []
    for _, row in df.iterrows():
        formatted_row = [format_value(val) for val in row]
        rows.append(formatted_row)

    return headers, rows


# Color palette for consistent styling (ice blue theme)
COLORS = {
    'primary': RGBColor(30, 80, 130),       # Dark steel blue
    'primary_dark': RGBColor(20, 60, 100),  # Darker blue
    'header_bg': RGBColor(45, 100, 150),    # Table header background (darker steel blue)
    'header_text': RGBColor(255, 255, 255), # Table header text (white)
    'row_alt': RGBColor(235, 245, 252),     # Alternating row (light ice blue)
    'row_normal': RGBColor(255, 255, 255),  # Normal row (white)
    'border': RGBColor(150, 180, 210),      # Table border (medium steel blue)
    'border_outer': RGBColor(45, 100, 150), # Outer table border (darker)
    'text_dark': RGBColor(51, 51, 51),      # Dark text
    'text_muted': RGBColor(102, 102, 102),  # Muted/caption text
    'group_header': RGBColor(51, 51, 51),   # Group header text (dark)
    'panel_title': RGBColor(80, 80, 80),    # Panel title text
}

# Table sizing
TABLE_WIDTH_RATIO = 0.85  # Table width as ratio of panel width


def add_table_to_slide(slide, table_data: tuple[list[str], list[list[str]]],
                       left: int, top: int, width: int, height: int,
                       width_ratio: float = TABLE_WIDTH_RATIO) -> None:
    """Add a styled table to the slide (narrower, centered, with borders)."""
    from lxml import etree

    headers, rows = table_data
    if not headers:
        return

    n_rows = len(rows) + 1  # +1 for header
    n_cols = len(headers)

    row_height = min(height // n_rows, Inches(0.18))

    # Make table narrower and centered
    actual_width = int(width * width_ratio)
    table_left = left + int((width - actual_width) / 2)

    table_shape = slide.shapes.add_table(n_rows, n_cols, table_left, top, actual_width, int(row_height * n_rows))
    table = table_shape.table

    # Clear table style to use simple borders
    graphic_frame = table_shape._element
    tbl = graphic_frame.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}tbl')
    tblPr = tbl.find('{http://schemas.openxmlformats.org/drawingml/2006/main}tblPr')
    if tblPr is not None:
        for styleId in tblPr.findall('{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId'):
            tblPr.remove(styleId)

    # Style header row
    for j, header in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = str(header)
        para = cell.text_frame.paragraphs[0]
        para.font.size = Pt(7)
        para.font.bold = True
        para.font.name = "Arial"
        para.alignment = PP_ALIGN.CENTER
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.fill.solid()
        cell.fill.fore_color.rgb = COLORS['header_bg']
        para.font.color.rgb = COLORS['header_text']
        # Set margins directly on cell (not text_frame)
        cell.margin_left = Inches(0.02)
        cell.margin_right = Inches(0.02)
        cell.margin_top = Inches(0.02)
        cell.margin_bottom = Inches(0.02)

    # Data rows with alternating colors and borders
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            cell = table.cell(i + 1, j)
            cell.text = str(value)
            para = cell.text_frame.paragraphs[0]
            para.font.size = Pt(6)
            para.font.name = "Arial"
            para.alignment = PP_ALIGN.CENTER
            para.font.color.rgb = COLORS['text_dark']
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if i % 2 == 0:
                cell.fill.fore_color.rgb = COLORS['row_normal']
            else:
                cell.fill.fore_color.rgb = COLORS['row_alt']
            # Set margins directly on cell
            cell.margin_left = Inches(0.02)
            cell.margin_right = Inches(0.02)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)


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
    run_dir: Path,
    snapshot_config: SnapshotSpec,
    template_path: Path,
    output_path: Path,
) -> None:
    """Generate a single-slide snapshot with multiple panels."""
    gene, indication = parse_run_dir(run_dir)
    click.echo(f"Generating panel snapshot for {gene} in {indication}")

    prs = load_presentation_from_template(template_path)

    # Use layout 9 for content slide
    slide_layout = prs.slide_layouts[9]
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

    # Calculate content area
    margin = Inches(0.3)
    bottom_margin = Inches(0.7)  # Extra space for footer
    panel_gap = Inches(0.2)
    content_width = slide_width - (2 * margin)
    content_height = slide_height - content_top - bottom_margin

    # Check for grouped layout
    if snapshot_config.layout.lower() == "grouped" and snapshot_config.groups:
        _render_grouped_layout(
            slide, snapshot_config.groups, run_dir, gene, indication,
            margin, content_top, content_width, content_height, panel_gap
        )
    else:
        _render_grid_layout(
            slide, snapshot_config.panels, snapshot_config.layout, run_dir, gene, indication,
            margin, content_top, content_width, content_height, panel_gap
        )

    prs.save(str(output_path))
    click.echo(f"  Saved: {output_path}")


def _render_grid_layout(
    slide, panels: list, layout: str, run_dir: Path, gene: str, indication: str,
    margin, content_top, content_width, content_height, panel_gap
) -> None:
    """Render panels in a grid layout."""
    rows, cols = parse_layout(layout)
    panel_width = (content_width - (cols - 1) * panel_gap) / cols
    panel_height = (content_height - (rows - 1) * panel_gap) / rows

    for idx, panel in enumerate(panels):
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
        has_title = bool(panel.title)

        # Reserve space for panel title if present
        title_height = Inches(0.3) if has_title else 0
        available_height = panel_height - title_height

        if has_figure and has_table:
            figure_height = available_height * 0.7
            table_height = available_height * 0.25
        elif has_figure:
            figure_height = available_height * 0.9
            table_height = 0
        else:
            figure_height = 0
            table_height = available_height * 0.7

        current_top = panel_top

        # Add panel title if present
        if panel.title:
            panel_title_text = substitute_placeholders(panel.title, gene, indication)
            panel_title_box = slide.shapes.add_textbox(
                int(panel_left), int(current_top), int(panel_width), int(title_height)
            )
            panel_title_frame = panel_title_box.text_frame
            panel_title_para = panel_title_frame.paragraphs[0]
            panel_title_para.text = panel_title_text
            panel_title_para.font.size = Pt(12)
            panel_title_para.font.bold = True
            panel_title_para.font.color.rgb = RGBColor(0, 51, 102)
            panel_title_para.alignment = PP_ALIGN.CENTER
            current_top += title_height

        # Add figure
        if panel.figure:
            fig_path = run_dir / panel.figure
            if not fig_path.exists():
                # Try without 'figures/' prefix
                fig_path = run_dir.parent / "figures" / panel.figure

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
            table_path = run_dir / panel.table
            if not table_path.exists():
                # Try in parent's tables directory
                table_path = run_dir.parent / "tables" / panel.table
            if not table_path.exists():
                # Try relative to figures dir
                table_path = run_dir.parent / panel.table

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
            caption_text = substitute_placeholders(panel.caption, gene, indication)
            caption_box = slide.shapes.add_textbox(
                int(panel_left), int(current_top), int(panel_width), Inches(0.25)
            )
            caption_frame = caption_box.text_frame
            caption_para = caption_frame.paragraphs[0]
            caption_para.text = caption_text
            caption_para.font.size = Pt(8)
            caption_para.font.name = "Arial"
            caption_para.font.italic = True
            caption_para.font.color.rgb = COLORS['text_muted']
            caption_para.alignment = PP_ALIGN.CENTER


def _render_grouped_layout(
    slide, groups: list, run_dir: Path, gene: str, indication: str,
    margin, content_top, content_width, content_height, panel_gap
) -> None:
    """Render panels in grouped columns layout."""
    n_groups = len(groups)
    if n_groups == 0:
        return

    group_gap = Inches(0.3)
    group_width = (content_width - (n_groups - 1) * group_gap) / n_groups
    group_header_height = Inches(0.35)

    for group_idx, group in enumerate(groups):
        group_left = margin + group_idx * (group_width + group_gap)
        group_top = content_top

        # Add group header
        if group.title:
            group_title_text = substitute_placeholders(group.title, gene, indication)
            header_box = slide.shapes.add_textbox(
                int(group_left), int(group_top), int(group_width), int(group_header_height)
            )
            header_frame = header_box.text_frame
            header_para = header_frame.paragraphs[0]
            header_para.text = group_title_text
            header_para.font.size = Pt(12)
            header_para.font.bold = True
            header_para.font.name = "Arial"
            header_para.font.color.rgb = COLORS['group_header']
            header_para.alignment = PP_ALIGN.CENTER

            # Add underline accent below group header
            from pptx.shapes.autoshape import Shape
            line = slide.shapes.add_shape(
                1,  # MSO_SHAPE.RECTANGLE
                int(group_left + group_width * 0.1),
                int(group_top + group_header_height - Inches(0.05)),
                int(group_width * 0.8),
                Inches(0.02)
            )
            line.fill.solid()
            line.fill.fore_color.rgb = COLORS['primary']
            line.line.fill.background()

            group_top += group_header_height

        # Calculate panel heights within this group
        n_panels = len(group.panels)
        if n_panels == 0:
            continue

        available_height = content_height - group_header_height

        # Smart height allocation: table-only panels get fixed height, figures expand
        panel_heights = []
        table_only_height = Inches(1.2)  # Fixed height for table-only panels

        figure_panels = []
        for idx, panel in enumerate(group.panels):
            has_figure = panel.figure is not None
            has_table = panel.table is not None

            if has_figure:
                figure_panels.append(idx)
                panel_heights.append(None)  # Will calculate later
            else:
                # Table-only panel gets fixed height
                panel_heights.append(table_only_height)

        # Calculate remaining height for figure panels
        fixed_height_total = sum(h for h in panel_heights if h is not None)
        gaps_total = (n_panels - 1) * panel_gap
        remaining_height = available_height - fixed_height_total - gaps_total

        if figure_panels:
            figure_panel_height = remaining_height / len(figure_panels)
            for idx in figure_panels:
                panel_heights[idx] = figure_panel_height

        # Render each panel in this group (stacked vertically)
        current_top = group_top
        for idx, panel in enumerate(group.panels):
            _render_single_panel(
                slide, panel, run_dir, gene, indication,
                int(group_left), int(current_top), int(group_width), int(panel_heights[idx])
            )
            current_top += panel_heights[idx] + panel_gap


def _render_single_panel(
    slide, panel: PanelSpec, run_dir: Path, gene: str, indication: str,
    panel_left: int, panel_top: int, panel_width: int, panel_height: int
) -> None:
    """Render a single panel at the specified position."""
    has_figure = panel.figure is not None
    has_table = panel.table is not None
    has_title = bool(panel.title)
    has_caption = bool(panel.caption)

    # Reserve space for panel title and caption
    title_height = Inches(0.25) if has_title else 0
    caption_height = Inches(0.2) if has_caption else 0
    available_height = panel_height - title_height - caption_height

    # Calculate fixed table height based on expected rows (tables stay constant size)
    # Row height ~0.18", header + data rows + small margin
    table_row_height = Inches(0.18)
    estimated_table_rows = min(panel.table_max_rows + 1, 8)  # +1 for header, cap at 8
    fixed_table_height = table_row_height * estimated_table_rows + Inches(0.1) if has_table else 0

    # Figures expand to fill remaining space
    if has_figure and has_table:
        table_height = fixed_table_height
        figure_height = available_height - table_height - Inches(0.1)  # gap between
    elif has_figure:
        figure_height = available_height * 0.95  # use most of the space
        table_height = 0
    else:
        figure_height = 0
        table_height = min(fixed_table_height, available_height * 0.8)

    current_top = panel_top

    # Add panel title if present
    if panel.title:
        panel_title_text = substitute_placeholders(panel.title, gene, indication)
        panel_title_box = slide.shapes.add_textbox(
            panel_left, current_top, panel_width, int(title_height)
        )
        panel_title_frame = panel_title_box.text_frame
        panel_title_para = panel_title_frame.paragraphs[0]
        panel_title_para.text = panel_title_text
        panel_title_para.font.size = Pt(9)
        panel_title_para.font.bold = True
        panel_title_para.font.name = "Arial"
        panel_title_para.font.color.rgb = COLORS['panel_title']
        panel_title_para.alignment = PP_ALIGN.CENTER
        current_top += int(title_height)

    # Add figure
    if panel.figure:
        # Look in figures/ subdirectory first, then try path as-is
        fig_path = run_dir / "figures" / panel.figure
        if not fig_path.exists():
            fig_path = run_dir / panel.figure

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
                current_top += int(actual_height) + Inches(0.05)

            except Exception as e:
                click.echo(f"  Warning: Could not add figure {panel.figure}: {e}", err=True)
        else:
            click.echo(f"  Warning: Figure not found: {panel.figure}", err=True)

    # Add table
    if panel.table:
        # Tables are in subskills/xxx/tables/ or figures/subskills/xxx/tables/
        table_path = run_dir / panel.table
        if not table_path.exists():
            table_path = run_dir / "figures" / panel.table

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
                                      panel_left, current_top,
                                      panel_width, int(table_height))
                    current_top += int(table_height) + Inches(0.05)
            except Exception as e:
                click.echo(f"  Warning: Could not add table {panel.table}: {e}", err=True)
        else:
            click.echo(f"  Warning: Table not found: {panel.table}", err=True)

    # Add caption
    if panel.caption:
        caption_text = substitute_placeholders(panel.caption, gene, indication)
        caption_box = slide.shapes.add_textbox(
            panel_left, current_top, panel_width, Inches(0.2)
        )
        caption_frame = caption_box.text_frame
        caption_para = caption_frame.paragraphs[0]
        caption_para.text = caption_text
        caption_para.font.size = Pt(8)
        caption_para.font.name = "Arial"
        caption_para.font.italic = True
        caption_para.font.color.rgb = COLORS['text_muted']
        caption_para.alignment = PP_ALIGN.CENTER


@click.command()
@click.option(
    "--run-dir", "-r",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to run directory (e.g., .../KRAS-COADREAD/2026-09-11__2.0.0__ba95ab6)",
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
    run_dir: Path,
    snapshot_config: Path,
    template: Path,
    output: Optional[Path],
) -> None:
    """Generate a single-slide snapshot with multiple panels."""
    config = load_snapshot_config(snapshot_config)

    if output is None:
        try:
            gene, indication = parse_run_dir(run_dir)
            output = Path(f"{gene}-{indication}-panel-snapshot.pptx")
        except ValueError:
            output = Path("panel-snapshot.pptx")

    generate_panel_snapshot(
        run_dir=run_dir,
        snapshot_config=config,
        template_path=template,
        output_path=output,
    )


if __name__ == "__main__":
    main()
