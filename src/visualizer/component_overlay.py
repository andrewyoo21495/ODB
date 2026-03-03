"""Component overlay rendering - outlines and reference designators."""

from __future__ import annotations

import math

from matplotlib.axes import Axes
from matplotlib.patches import FancyBboxPatch, Rectangle

from src.models import BBox, Component, EdaData, Package


def draw_components(ax: Axes, components: list[Component],
                    packages: list[Package] = None,
                    color: str = "#00CCCC", alpha: float = 0.5,
                    show_labels: bool = True, font_size: float = 4):
    """Draw component outlines and reference designators.

    Args:
        ax: matplotlib Axes
        components: List of placed components
        packages: List of package definitions (for outline shapes)
        color: Outline color
        alpha: Opacity
        show_labels: Whether to show reference designator labels
        font_size: Label font size
    """
    pkg_lookup = {}
    if packages:
        pkg_lookup = {i: pkg for i, pkg in enumerate(packages)}

    for comp in components:
        pkg = pkg_lookup.get(comp.pkg_ref)
        bbox = _get_component_bbox(comp, pkg)

        if bbox:
            _draw_comp_outline(ax, comp, bbox, color, alpha)

        if show_labels:
            ax.annotate(
                comp.comp_name,
                (comp.x, comp.y),
                fontsize=font_size,
                color=color,
                alpha=min(1.0, alpha + 0.3),
                ha="center", va="center",
                fontweight="bold",
            )


def draw_pin_markers(ax: Axes, components: list[Component],
                     color: str = "#FF4444", size: float = 0.002):
    """Draw small markers at component pin locations."""
    for comp in components:
        for toep in comp.toeprints:
            ax.plot(toep.x, toep.y, ".", color=color, markersize=1, alpha=0.5)


def _get_component_bbox(comp: Component, pkg: Package = None) -> BBox | None:
    """Calculate the bounding box of a component in board coordinates."""
    if pkg and pkg.bbox:
        # Transform package bbox to board coordinates
        bx = pkg.bbox
        hw = (bx.xmax - bx.xmin) / 2
        hh = (bx.ymax - bx.ymin) / 2
        cx = (bx.xmax + bx.xmin) / 2
        cy = (bx.ymax + bx.ymin) / 2

        # Apply rotation
        angle = math.radians(-comp.rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        # Get rotated corners
        corners = [
            (-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)
        ]

        if comp.mirror:
            corners = [(x, -y) for x, y in corners]

        rotated = [
            (x * cos_a - y * sin_a + comp.x,
             x * sin_a + y * cos_a + comp.y)
            for x, y in corners
        ]

        xs = [p[0] for p in rotated]
        ys = [p[1] for p in rotated]

        return BBox(min(xs), min(ys), max(xs), max(ys))

    # Fallback: estimate from toeprints
    if comp.toeprints:
        xs = [t.x for t in comp.toeprints]
        ys = [t.y for t in comp.toeprints]
        margin = 0.005  # Small margin around pins
        return BBox(
            min(xs) - margin, min(ys) - margin,
            max(xs) + margin, max(ys) + margin,
        )

    return None


def _draw_comp_outline(ax: Axes, comp: Component, bbox: BBox,
                       color: str, alpha: float):
    """Draw the component outline rectangle."""
    w = bbox.xmax - bbox.xmin
    h = bbox.ymax - bbox.ymin

    rect = Rectangle(
        (bbox.xmin, bbox.ymin), w, h,
        linewidth=0.5, edgecolor=color, facecolor="none",
        alpha=alpha, linestyle="--",
    )
    ax.add_patch(rect)
