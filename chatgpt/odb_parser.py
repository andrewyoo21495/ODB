####################################################################################
# 3) odb_parser.py

## 전체 ODB++ tree 로더. 
# eda/data에서 PKG/PIN/NET/SNT/FID를 파싱해 project.net_fid_map을 구축하고, 각 layer의 features 파일을 읽어 symbol table을 구성합니다. 
# Feature 레코드에서 FID 추출을 시도합니다.
####################################################################################

# odb_parser.py
import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from symbol_parser import parse_symbols, Symbol
from geom_builder import pad_feature_to_polygon
from shapely.geometry import Polygon, Point

"""
ODB++ simplified parser focused on:
 - Parsing eda/data for NET/SNT/FID relationships
 - Parsing layer features (including $SYMBOL sections)
 - Extracting P (pad) features and building symbol tables per layer

Note: This is not a full ODB++ parser for every record type, but it covers the common essentials needed for DRC & visualization.
"""

@dataclass
class LayerFeature:
    fnum: int
    record_type: str
    params: List[str]
    raw_line: str = ''
    attrs: Dict[str, str] = field(default_factory=dict)  # e.g., FID from ';FID=...'

@dataclass
class Layer:
    name: str
    features: List[LayerFeature] = field(default_factory=list)
    symbols: Dict[int, Symbol] = field(default_factory=dict)
    units: str = 'IN'  # default; features file may specify UNITS=...

@dataclass
class Package:
    name: str
    pins: List[Any] = field(default_factory=list)

@dataclass
class Net:
    name: str
    id: Optional[int] = None
    snt_records: List[str] = field(default_factory=list)
    fids: List[int] = field(default_factory=list)  # FIDs associated with this net

@dataclass
class ODBProject:
    root_dir: str
    step: str = ''
    layers: Dict[str, Layer] = field(default_factory=dict)
    nets: List[Net] = field(default_factory=list)
    # reverse map: fid -> net index
    fid_to_net: Dict[int, int] = field(default_factory=dict)
    # optional: list of pad polygons with info
    pads: List[Dict] = field(default_factory=list)

def _extract_trailing_attrs(line: str) -> Dict[str,str]:
    """
    Many feature/eda lines contain trailing attributes separated by ';' or within.
    This function extracts tokens like 'FID=123' or 'ID=...' or 'ATTR=...'
    """
    attrs = {}
    if ';' in line:
        parts = line.split(';')
        for part in parts[1:]:
            if '=' in part:
                k,v = part.split('=',1)
                attrs[k.strip().upper()] = v.strip()
            else:
                # bare token
                t = part.strip()
                if t:
                    attrs[t.upper()] = t
    # Also capture inline 'FID=<n>' patterns
    mo = re.search(r"FID\s*=\s*([0-9]+)", line, re.IGNORECASE)
    if mo:
        attrs['FID'] = mo.group(1)
    # pattern "F <num>" or "f <num>"
    mo2 = re.search(r"\bF\s*([0-9]+)\b", line)
    if mo2 and 'FID' not in attrs:
        attrs['FID'] = mo2.group(1)
    return attrs

def parse_eda_data(eda_data_path: str, project: ODBProject):
    """
    Parse eda/data for NET, SNT and FID mapping.
    - NET <name> : starts net record
    - SNT ...   : store as raw record inside net
    - FID <id>  : sometimes appear; in some ODB++ variants FID mapping appears as FID <num> <netname>
    The parsing is heuristic to capture common patterns.
    """
    if not os.path.exists(eda_data_path):
        return project
    with open(eda_data_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    curr_net = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        tokens = line.split()
        kw = tokens[0].upper()
        if kw == 'NET':
            name = tokens[1] if len(tokens) > 1 else f"net_{len(project.nets)}"
            curr_net = Net(name)
            project.nets.append(curr_net)
            continue
        if kw == 'SNT':
            if curr_net is not None:
                curr_net.snt_records.append(line)
            continue
        # Some files list FID mapping lines like: "FID 123 NAME=... NET=..."
        if kw == 'FID':
            try:
                fid = int(tokens[1])
                # try to find net name in same line
                mo = re.search(r"NET\s*=\s*([^\s;]+)", line, re.IGNORECASE)
                netname = mo.group(1) if mo else None
                if netname:
                    # find net index
                    for i,n in enumerate(project.nets):
                        if n.name == netname:
                            project.fid_to_net[fid] = i
                            project.nets[i].fids.append(fid)
                            break
                else:
                    # store into a pending mapping keyed by fid but no net
                    project.fid_to_net[fid] = -1
            except:
                pass
            continue
        # Some vendors include "FID=123" at end of SNT; we will pick them when parsing features
    # end for
    return project

def parse_layer_features(features_file_path: str) -> Optional[Layer]:
    """
    Parse a layer's features file: capture:
     - $SYMBOL blocks (via symbol_parser)
     - feature records (P, L, A, RC, CR, OB, OC, OS, OE, SQ, etc)
     - capture trailing attributes (e.g., ;FID=123)
    Returns Layer object.
    """
    if not os.path.exists(features_file_path):
        return None
    with open(features_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    # parse symbols
    symbols = parse_symbols(lines)

    layer = Layer(name=os.path.basename(os.path.dirname(features_file_path)))
    layer.symbols = symbols

    # parse records
    feature_re = re.compile(r"^([A-Za-z]{1,3})\s+(.*)$")
    fnum = 0
    for raw in lines:
        line = raw.rstrip('\n')
        if not line or line.strip().startswith('#') or line.strip().startswith('$'):
            continue
        m = feature_re.match(line.strip())
        if not m:
            continue
        rtype = m.group(1).upper()
        params_str = m.group(2)
        # split on whitespace but preserve tokens like 'X=12;FID=123' -> we'll keep raw line as well
        params = params_str.split()
        attrs = _extract_trailing_attrs(line)
        lf = LayerFeature(fnum, rtype, params, raw_line=line, attrs=attrs)
        layer.features.append(lf)
        fnum += 1

    return layer

def load_odb_tree(root_dir: str, step_name: Optional[str] = None) -> ODBProject:
    """
    Load an ODB++ folder tree rooted at root_dir.
    Looks for steps/<step>/eda/...
    """
    proj = ODBProject(root_dir)
    steps_dir = os.path.join(root_dir, 'steps')
    if not os.path.isdir(steps_dir):
        raise FileNotFoundError(f"steps folder not found under {root_dir}")
    steps = [d for d in os.listdir(steps_dir) if os.path.isdir(os.path.join(steps_dir, d))]
    if not steps:
        raise FileNotFoundError("no steps found under steps/")
    step = step_name or steps[0]
    proj.step = step
    eda_dir = os.path.join(steps_dir, step, 'eda')
    if not os.path.isdir(eda_dir):
        raise FileNotFoundError(f"eda folder not found under {os.path.join(steps_dir, step)}")
    # parse eda/data
    eda_data = os.path.join(eda_dir, 'data')
    if os.path.exists(eda_data):
        parse_eda_data(eda_data, proj)
    # parse layers: look for subdirs that contain 'features'
    for entry in os.listdir(eda_dir):
        path = os.path.join(eda_dir, entry)
        if os.path.isdir(path):
            feat_file = os.path.join(path, 'features')
            if os.path.exists(feat_file):
                layer = parse_layer_features(feat_file)
                if layer:
                    proj.layers[entry] = layer
    # Build reverse fid->net map from nets with known fids
    for ni, net in enumerate(proj.nets):
        for fid in net.fids:
            proj.fid_to_net[fid] = ni

    # collect pad polygons and associate FID if possible (we'll attempt to find FID via feature.attrs or inline tokens)
    proj.pads = []
    for lname, layer in proj.layers.items():
        for feat in layer.features:
            if feat.record_type == 'P':
                # create polygon
                poly = pad_feature_to_polygon(feat, layer.symbols)
                if poly is None:
                    continue
                # try to find FID
                fid = None
                if 'FID' in feat.attrs:
                    try:
                        fid = int(feat.attrs['FID'])
                    except:
                        fid = None
                else:
                    # attempt to find FID token in raw_line (pattern 'FID=123' or 'f 123')
                    mo = re.search(r"FID\s*=\s*([0-9]+)", feat.raw_line, re.IGNORECASE)
                    if mo:
                        fid = int(mo.group(1))
                    else:
                        mo2 = re.search(r"\bF\s*([0-9]+)\b", feat.raw_line)
                        if mo2:
                            try:
                                fid = int(mo2.group(1))
                            except:
                                fid = None
                # map fid to net index if possible
                net_index = None
                if fid is not None:
                    net_index = proj.fid_to_net.get(fid, None)
                # store
                proj.pads.append({
                    'layer': lname,
                    'feature': feat,
                    'poly': poly,
                    'fid': fid,
                    'net_index': net_index
                })
    return proj

# Quick run demo (if run directly)
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        root = sys.argv[1]
        p = load_odb_tree(root)
        print("Loaded project. Layers:", list(p.layers.keys()))
        print("Nets:", [n.name for n in p.nets])
        print("Pad count:", len(p.pads))
    else:
        print("Usage: python odb_parser.py <odb_root_dir>")
