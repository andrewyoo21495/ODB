"""FID-based pin-to-feature lookup for accurate pad rendering.

Instead of matching pads by spatial position (toeprint x,y), this module
resolves pin geometry through the ODB++ Feature ID cross-reference chain:

    EDA/data SNT(TOP) → FID(layer_idx, feature_idx) → Layer features file

Steps:
  1. Build a map from (comp_num, pin_num) to FeatureIdRef list from EDA nets.
  2. Map each FID's layer_idx to the actual layer name via eda_data.layer_names.
  3. Look up the referenced feature (PadRecord) and its symbol in the layer.
  4. Return resolved records ready for rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.models import (
    EdaData, FeatureIdRef, LayerFeatures, MatrixLayer, PadRecord, SymbolRef,
)


# ---------------------------------------------------------------------------
# Resolved FID feature — everything needed to render one pin pad
# ---------------------------------------------------------------------------

@dataclass
class ResolvedPadFeature:
    """A fully resolved pad feature from a FID cross-reference."""
    pad: PadRecord
    symbol: SymbolRef
    layer_name: str
    units: str = "INCH"


# ---------------------------------------------------------------------------
# Layer name standardisation (sigt / sigb mapper)
# ---------------------------------------------------------------------------

def build_layer_name_map(
    eda_layer_names: list[str],
    matrix_layers: dict[str, MatrixLayer] | None = None,
) -> dict[int, str]:
    """Map EDA layer indices to canonical layer names.

    The EDA/data LYR record lists layer names by index (0-based).
    This function returns ``{layer_idx: layer_name}`` and applies the
    *sigt/sigb* standardisation rule:

      * If no layer is explicitly named ``sigt`` or ``sigb`` among the
        SIGNAL-type layers, the signal layer whose trailing number is
        **lowest** is designated *sigt* (top signal) and the one whose
        trailing number is **highest** is designated *sigb* (bottom signal).

    These aliases are only informational; the returned dict always uses the
    **original** layer names so that callers can look them up in layers_data.
    """
    name_map: dict[int, str] = {}
    for idx, name in enumerate(eda_layer_names):
        name_map[idx] = name
    return name_map


_TRAILING_NUM_RE = re.compile(r"(\d+)$")


def identify_signal_layers(
    eda_layer_names: list[str],
    matrix_layers: dict[str, MatrixLayer] | None = None,
) -> dict[str, str]:
    """Return ``{"sigt": <name>, "sigb": <name>}`` for signal-layer aliases.

    Rules:
      * If a layer is already named exactly ``sigt`` or ``sigb``, use it.
      * Otherwise, among layers starting with ``sig`` and ending with a number
        (e.g. sig_1, signal_2, sig10), pick the one with the lowest trailing
        number as *sigt* and the highest as *sigb*.
    """
    result: dict[str, str] = {}

    # Check for explicit names first
    name_set = {n.lower() for n in eda_layer_names}
    if "sigt" in name_set:
        result["sigt"] = "sigt"
    if "sigb" in name_set:
        result["sigb"] = "sigb"
    if len(result) == 2:
        return result

    # Collect signal layers that start with "sig" and end with a number
    signal_layers: list[tuple[int, str]] = []
    for name in eda_layer_names:
        lower = name.lower()
        if lower.startswith("sig"):
            m = _TRAILING_NUM_RE.search(name)
            if m:
                signal_layers.append((int(m.group(1)), name))

    if signal_layers:
        signal_layers.sort(key=lambda t: t[0])
        if "sigt" not in result:
            result["sigt"] = signal_layers[0][1]
        if "sigb" not in result:
            result["sigb"] = signal_layers[-1][1]

    return result


# ---------------------------------------------------------------------------
# FID map builder
# ---------------------------------------------------------------------------

def build_fid_map(
    eda_data: EdaData,
) -> dict[tuple[str, int, int], list[FeatureIdRef]]:
    """Build a mapping from (side, comp_num, pin_num) → [FeatureIdRef].

    Iterates all NET → SNT(type=TOP) records in *eda_data* and collects
    their FID cross-references.

    Keys:
      * ``side``: "T" (top) or "B" (bottom)
      * ``comp_num``: component index in the components file (0-based)
      * ``pin_num``:  toeprint/pin number within the component
    """
    fid_map: dict[tuple[str, int, int], list[FeatureIdRef]] = {}

    for net in eda_data.nets:
        for subnet in net.subnets:
            if subnet.type != "TOP":
                continue
            if not subnet.feature_ids:
                continue
            key = (subnet.side, subnet.comp_num, subnet.toep_num)
            existing = fid_map.get(key)
            if existing is None:
                fid_map[key] = list(subnet.feature_ids)
            else:
                existing.extend(subnet.feature_ids)

    return fid_map


# ---------------------------------------------------------------------------
# Resolve FID references to actual pad features
# ---------------------------------------------------------------------------

def resolve_fid_features(
    fid_map: dict[tuple[str, int, int], list[FeatureIdRef]],
    eda_layer_names: list[str],
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
) -> dict[tuple[str, int, int], list[ResolvedPadFeature]]:
    """Resolve every FID reference to its actual PadRecord + SymbolRef.

    Returns a dict with the same keys as *fid_map* but values are lists of
    :class:`ResolvedPadFeature` that carry the pad geometry, its symbol,
    layer name, and units — everything needed to render the pin.

    Only FIDs of type ``"C"`` (copper) that point to a valid PadRecord are
    included; other types (Laminate, Hole) are skipped.
    """
    layer_name_map = build_layer_name_map(eda_layer_names)

    # Pre-build per-layer feature index and symbol lookup
    _layer_cache: dict[str, tuple[list, dict[int, SymbolRef], str]] = {}
    for lname, (lf, _ml) in layers_data.items():
        sym_lookup = {s.index: s for s in lf.symbols}
        _layer_cache[lname] = (lf.features, sym_lookup, lf.units)

    resolved: dict[tuple[str, int, int], list[ResolvedPadFeature]] = {}

    for key, fid_list in fid_map.items():
        pad_list: list[ResolvedPadFeature] = []
        for fid in fid_list:
            if fid.type != "C":
                continue

            layer_name = layer_name_map.get(fid.layer_idx)
            if layer_name is None:
                continue

            cached = _layer_cache.get(layer_name)
            if cached is None:
                continue

            features, sym_lookup, units = cached
            if fid.feature_idx < 0 or fid.feature_idx >= len(features):
                continue

            feat = features[fid.feature_idx]
            if not isinstance(feat, PadRecord):
                continue

            sym = sym_lookup.get(feat.symbol_idx)
            if sym is None:
                continue

            pad_list.append(ResolvedPadFeature(
                pad=feat, symbol=sym, layer_name=layer_name, units=units,
            ))

        if pad_list:
            resolved[key] = pad_list

    return resolved


# ---------------------------------------------------------------------------
# VIA detection via .pad_usage attribute  (preferred)
# ---------------------------------------------------------------------------

def _find_top_bottom_signal_layers(
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
) -> tuple[Optional[str], Optional[str]]:
    """Return (top_signal_name, bottom_signal_name) from the matrix stackup.

    Priority:
      1. If a SIGNAL layer is named exactly ``sigt``, it is the top layer.
         If a SIGNAL layer is named exactly ``sigb``, it is the bottom layer.
      2. Otherwise, among SIGNAL layers starting with ``sig`` and ending with a
         number (e.g. sig_1, signal_2, sig10), the lowest number is top and the
         highest number is bottom.

    Returns ``(None, None)`` if fewer than two signal layers exist.
    """
    signal_names = [
        name for name, (_lf, ml) in layers_data.items()
        if ml.type == "SIGNAL"
    ]
    if len(signal_names) < 2:
        return None, None

    # 1. Explicit sigt / sigb names take priority
    name_set = {n.lower() for n in signal_names}
    top = "sigt" if "sigt" in name_set else None
    bot = "sigb" if "sigb" in name_set else None

    # 2. Fall back: among layers starting with "sig" and ending with a number,
    #    lowest number → top, highest number → bottom
    if top is None or bot is None:
        numbered: list[tuple[int, str]] = []
        for name in signal_names:
            if name.lower().startswith("sig"):
                m = _TRAILING_NUM_RE.search(name)
                if m:
                    numbered.append((int(m.group(1)), name))
        if numbered:
            numbered.sort(key=lambda t: t[0])
            if top is None:
                top = numbered[0][1]
            if bot is None:
                bot = numbered[-1][1]

    return top, bot


def collect_via_pads_by_attribute(
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
) -> list[ResolvedPadFeature]:
    """Collect VIA pads from the top and bottom signal layers using ``.pad_usage``.

    In ODB++ feature files each pad record carries a ``.pad_usage`` attribute
    whose *raw* numeric value indicates the pad type:

      * **0** — toeprint (standard component pad)
      * **1** — via

    The feature parser resolves the raw value through the ``&N`` text table,
    so the stored attribute is a text string.  To match raw value 1 we look
    up ``attr_texts[1]`` for the layer's text table and compare.

    Only the outermost signal layers (lowest and highest matrix row) are
    scanned, since via-on-pad verification targets component pads on these
    outer layers.
    """
    top_name, bot_name = _find_top_bottom_signal_layers(layers_data)
    if top_name is None:
        return []

    target_names = {top_name, bot_name}
    result: list[ResolvedPadFeature] = []

    for layer_name in target_names:
        lf, _ml = layers_data[layer_name]
        sym_lookup = {s.index: s for s in lf.symbols}

        # The resolved text for raw value 1 (via) in this layer's text table
        via_text = lf.attr_texts.get(1)

        for feat in lf.features:
            if not isinstance(feat, PadRecord):
                continue

            pu = feat.attributes.get(".pad_usage")
            if pu is None:
                continue

            # Match raw value 1: resolved to via_text, or stored as "1"
            # when the text table has no entry for index 1
            if pu != via_text and pu != "1":
                continue

            sym = sym_lookup.get(feat.symbol_idx)
            if sym is None:
                continue

            result.append(ResolvedPadFeature(
                pad=feat, symbol=sym, layer_name=layer_name, units=lf.units,
            ))

    return result


# ---------------------------------------------------------------------------
# VIA subnet FID resolution  (fallback when .pad_usage is unavailable)
# ---------------------------------------------------------------------------

def build_via_fid_list(
    eda_data: EdaData,
) -> list[FeatureIdRef]:
    """Collect all FID references from VIA-type subnets.

    VIA subnets represent through-board via connections and carry FID
    references to pad features on one or more copper layers.  Unlike TOP
    subnets they have no side/comp_num/toep_num fields — they are purely
    layer-feature pointers.

    Returns a flat list of :class:`FeatureIdRef` records (type ``"C"`` only).
    """
    fid_list: list[FeatureIdRef] = []
    for net in eda_data.nets:
        for subnet in net.subnets:
            if subnet.type != "VIA":
                continue
            for fid in subnet.feature_ids:
                if fid.type == "C":
                    fid_list.append(fid)
    return fid_list


def resolve_via_features(
    eda_data: EdaData,
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
) -> list[ResolvedPadFeature]:
    """Resolve VIA subnet FIDs to renderable pad features.

    Returns a deduplicated list of :class:`ResolvedPadFeature` — one per
    unique (x, y) board position — suitable for drawing via pads.
    """
    fid_list = build_via_fid_list(eda_data)
    if not fid_list:
        return []

    layer_name_map = build_layer_name_map(eda_data.layer_names)

    _layer_cache: dict[str, tuple[list, dict[int, SymbolRef], str]] = {}
    for lname, (lf, _ml) in layers_data.items():
        sym_lookup = {s.index: s for s in lf.symbols}
        _layer_cache[lname] = (lf.features, sym_lookup, lf.units)

    seen_layer_positions: set[tuple[str, float, float]] = set()
    result: list[ResolvedPadFeature] = []

    for fid in fid_list:
        layer_name = layer_name_map.get(fid.layer_idx)
        if layer_name is None:
            continue

        cached = _layer_cache.get(layer_name)
        if cached is None:
            continue

        features, sym_lookup, units = cached
        if fid.feature_idx < 0 or fid.feature_idx >= len(features):
            continue

        feat = features[fid.feature_idx]
        if not isinstance(feat, PadRecord):
            continue

        pos_key = (layer_name, round(feat.x, 4), round(feat.y, 4))
        if pos_key in seen_layer_positions:
            continue
        seen_layer_positions.add(pos_key)

        sym = sym_lookup.get(feat.symbol_idx)
        if sym is None:
            continue

        result.append(ResolvedPadFeature(
            pad=feat, symbol=sym, layer_name=layer_name, units=units,
        ))

    return result


# ---------------------------------------------------------------------------
# Collect FID-referenced layer names (for selective loading)
# ---------------------------------------------------------------------------

def collect_fid_layer_names(
    eda_data: EdaData,
) -> set[str]:
    """Return the set of layer names referenced by any FID record.

    This lets the loader know which layers *must* be loaded even if the
    user didn't explicitly request them, because they contain pin pad
    features needed for component visualisation.
    """
    referenced_indices: set[int] = set()

    for net in eda_data.nets:
        for subnet in net.subnets:
            if subnet.type != "TOP":
                continue
            for fid in subnet.feature_ids:
                if fid.type == "C":
                    referenced_indices.add(fid.layer_idx)

    layer_name_map = build_layer_name_map(eda_data.layer_names)
    return {
        layer_name_map[idx]
        for idx in referenced_indices
        if idx in layer_name_map
    }


# ---------------------------------------------------------------------------
# Collect specific feature indices per layer (for selective loading)
# ---------------------------------------------------------------------------

def collect_fid_feature_indices(
    eda_data: EdaData,
) -> dict[str, set[int]]:
    """Return ``{layer_name: {feature_idx, ...}}`` for all FID records.

    When loading layer features, the parser can use this to skip features
    that are not referenced, significantly reducing memory usage for large
    designs where only a fraction of features belong to component pins.
    """
    per_layer: dict[int, set[int]] = {}

    for net in eda_data.nets:
        for subnet in net.subnets:
            if subnet.type != "TOP":
                continue
            for fid in subnet.feature_ids:
                if fid.type == "C":
                    s = per_layer.get(fid.layer_idx)
                    if s is None:
                        per_layer[fid.layer_idx] = {fid.feature_idx}
                    else:
                        s.add(fid.feature_idx)

    layer_name_map = build_layer_name_map(eda_data.layer_names)
    return {
        layer_name_map[idx]: indices
        for idx, indices in per_layer.items()
        if idx in layer_name_map
    }
