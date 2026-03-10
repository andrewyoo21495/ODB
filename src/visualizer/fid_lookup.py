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
      * Otherwise, among SIGNAL-type layers (or names containing ``signal``),
        pick the one with the lowest trailing number as *sigt* and the
        highest as *sigb*.
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

    # Collect signal layers with trailing numbers
    signal_layers: list[tuple[int, str]] = []
    for name in eda_layer_names:
        is_signal = False
        if matrix_layers and name in matrix_layers:
            is_signal = matrix_layers[name].type == "SIGNAL"
        else:
            is_signal = "signal" in name.lower()

        if is_signal:
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
