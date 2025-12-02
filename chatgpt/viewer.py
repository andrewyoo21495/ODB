####################################################################################
# 5) viewer.py
# matplotlib으로 레이어를 시각화하고, pad 클릭 시 상세정보(패드 인덱스/NET/FID 등)를 표시합니다.
####################################################################################


# viewer.py
import matplotlib.pyplot as plt
from shapely.geometry import Polygon, Point
from descartes import PolygonPatch
import math

"""
Simple matplotlib viewer that displays pad polygons per layer.
Clicking near a pad prints details to stdout.
"""

def draw_layer(project, layer_name: str):
    layer = project.layers.get(layer_name)
    if layer is None:
        print("Layer not found:", layer_name)
        return
    fig, ax = plt.subplots(figsize=(10,8))
    # draw pads from project.pads filtered by layer
    pad_positions = []
    for i,p in enumerate(project.pads):
        if p['layer'] != layer_name:
            continue
        poly = p['poly']
        patch = PolygonPatch(poly, alpha=0.6)
        ax.add_patch(patch)
        # place label at centroid
        c = poly.centroid
        ax.text(c.x, c.y, str(i), fontsize=6, ha='center', va='center')
        pad_positions.append((i, poly, p))
    ax.set_aspect('equal', 'box')
    ax.set_title(f"Layer {layer_name}")
    # click handler
    def onclick(event):
        if event.inaxes != ax: return
        px, py = event.xdata, event.ydata
        best = None; bestd = float('inf')
        for idx, poly, info in pad_positions:
            d = Point(px,py).distance(poly)
            if d < bestd:
                bestd = d; best = (idx, poly, info)
        if best and bestd < 0.2:  # threshold: tune to your units
            idx, poly, info = best
            net_idx = info.get('net_index')
            net_name = project.nets[net_idx].name if (net_idx is not None and net_idx >= 0 and net_idx < len(project.nets)) else 'UNKNOWN'
            print(f"Clicked pad {idx} layer={info['layer']} fid={info['fid']} net={net_name} centroid=({poly.centroid.x:.4f},{poly.centroid.y:.4f})")
    cid = fig.canvas.mpl_connect('button_press_event', onclick)
    plt.show()

# if run directly: demo
if __name__ == "__main__":
    import sys
    from odb_parser import load_odb_tree
    if len(sys.argv) < 3:
        print("Usage: python viewer.py <odb_root> <layer_name>")
    else:
        proj = load_odb_tree(sys.argv[1])
        draw_layer(proj, sys.argv[2])
