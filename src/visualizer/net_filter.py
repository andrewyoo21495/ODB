"""Net-based feature filtering for signal layer visualization."""

from __future__ import annotations

from dataclasses import replace

from src.models import EdaData, LayerFeatures, MatrixLayer

# net_name → { layer_name → set[feature_idx] }
NetFeatureIndex = dict[str, dict[str, set[int]]]


def build_net_feature_index(
    eda_data: EdaData,
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
) -> NetFeatureIndex:
    """Build reverse mapping: net_name → { layer_name → set[feature_idx] }.

    Only includes layers present in layers_data.
    """
    if not eda_data or not eda_data.nets:
        return {}

    layer_names = eda_data.layer_names
    index: NetFeatureIndex = {}

    for net in eda_data.nets:
        net_entry: dict[str, set[int]] = {}
        for subnet in net.subnets:
            for fid_ref in subnet.feature_ids:
                if fid_ref.layer_idx >= len(layer_names):
                    continue
                layer_name = layer_names[fid_ref.layer_idx]
                if layer_name not in layers_data:
                    continue
                net_entry.setdefault(layer_name, set()).add(fid_ref.feature_idx)
        if net_entry:
            index[net.name] = net_entry

    return index


def get_signal_layers(
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
) -> list[str]:
    """Return SIGNAL layer names sorted by stack-up row order."""
    signal = [
        (name, ml.row)
        for name, (_, ml) in layers_data.items()
        if ml.type == "SIGNAL"
    ]
    signal.sort(key=lambda x: x[1])
    return [name for name, _ in signal]


def get_nets_for_layer(
    layer_name: str,
    net_feature_index: NetFeatureIndex,
) -> list[str]:
    """Return sorted net names that have features on layer_name."""
    return sorted(
        net for net, layers in net_feature_index.items()
        if layer_name in layers
    )


def filter_layer_features(
    layer_features: LayerFeatures,
    allowed_indices: set[int],
) -> LayerFeatures:
    """Return a copy of LayerFeatures containing only features at allowed_indices."""
    filtered = [
        f for i, f in enumerate(layer_features.features)
        if i in allowed_indices
    ]
    return replace(layer_features, features=filtered)
