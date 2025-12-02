# odb_parser.py
import os
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Iterable
from collections import defaultdict

# ---------------- Domain models ----------------
@dataclass
class Pin:
    name: str
    type_: str
    xc: float
    yc: float
    fhs: float
    etype: str
    mtype: str
    id: Optional[int] = None
    outlines: List[dict] = field(default_factory=list)  # e.g. [{'type':'RC', 'x':..., ...}, ...]

@dataclass
class Package:
    name: str
    pitch: float
    xmin: float; ymin: float; xmax: float; ymax: float
    id: Optional[int] = None
    pins: List[Pin] = field(default_factory=list)
    outlines: List[dict] = field(default_factory=list)

@dataclass
class Component:
    idx: int
    name: str
    x: float; y: float
    rot: float
    mirror: str  # 'N' or 'M'
    pkg_ref: int   # index into packages list
    side: str      # 'T'/'B' or as CMP record
    props: Dict = field(default_factory=dict)

@dataclass
class LayerFeature:
    fnum: int
    record_type: str  # 'P','L','A','RC','CR'...
    params: List
    attrs: Dict = field(default_factory=dict)

@dataclass
class Layer:
    name: str
    features: List[LayerFeature] = field(default_factory=list)
    units: str = 'IN'  # or 'MM'

@dataclass
class Net:
    name: str
    id: Optional[int] = None
    snt_records: List[dict] = field(default_factory=list)

@dataclass
class ODBProject:
    root_dir: str
    packages: List[Package] = field(default_factory=list)
    components_top: List[Component] = field(default_factory=list)
    components_bot: List[Component] = field(default_factory=list)
    layers: Dict[str, Layer] = field(default_factory=dict)
    nets: List[Net] = field(default_factory=list)

# ----------------- Parsers -----------------
def parse_eda_data(filepath: str, project: ODBProject):
    """
    Parse steps/<step>/eda/data (eda/data) for PKG, PIN, NET, SNT, FID etc.
    This is a robust-but-simple parser that handles common cases used in workflows.
    See spec: PKG/PIN/RC/CR/OB etc. :contentReference[oaicite:6]{index=6}
    """
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [ln.rstrip() for ln in f]
    curr_pkg = None
    for line in lines:
        if not line or line.startswith('#'): continue
        tok = line.split()
        kw = tok[0].upper()
        if kw == 'PKG':
            # PKG <name> <pitch> <xmin> <ymin> <xmax> <ymax>;...;ID=...
            name = tok[1]; pitch = float(tok[2]); xmin=float(tok[3]); ymin=float(tok[4]); xmax=float(tok[5]); ymax=float(tok[6])
            curr_pkg = Package(name, pitch, xmin,ymin,xmax,ymax)
            project.packages.append(curr_pkg)
        elif kw in ('RC','CR','SQ','CT','OB'):
            if curr_pkg is not None:
                # attach to most recent package or pin depending on context (outline follows PKG or PIN)
                curr_pkg.outlines.append({'type':kw, 'tokens':tok[1:]})
        elif kw == 'PIN':
            # PIN <name> <type> <xc> <yc> <fhs> <etype> <mtype> ID=<id>
            name=tok[1]; type_=tok[2]; xc=float(tok[3]); yc=float(tok[4]); fhs=float(tok[5]); etype=tok[6]; mtype=tok[7]
            pid = None
            for t in tok[8:]:
                if t.startswith('ID='):
                    try: pid=int(t.split('=')[1]); break
                    except: pass
            pin = Pin(name,type_,xc,yc,fhs,etype,mtype,id=pid)
            if curr_pkg:
                curr_pkg.pins.append(pin)
        elif kw == 'NET':
            # NET <name> ...
            name = tok[1] if len(tok)>1 else f"net_{len(project.nets)}"
            project.nets.append(Net(name))
        elif kw == 'SNT':
            # store raw SNT for net -> features mapping later
            if project.nets:
                project.nets[-1].snt_records.append({'tokens':tok[1:]})
        # (추가 처리: FID, PRP, etc. 필요시 확장)
    return project

def parse_layer_features(layer_dir: str, layer_name: str, project: ODBProject):
    """
    Parse <layer>/features (compressed/uncompressed plain text). 
    Features file contains sections: $ (symbols), @ (attrs), & (attr text), and records L,P,A,RC,CR etc.
    See spec: Layer features section.  
    """
    features_file = os.path.join(layer_dir, 'features')
    if not os.path.exists(features_file):
        return
    with open(features_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    layer = Layer(name=layer_name)
    fnum = 0
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith('#'): continue
        parts = ln.split()
        rtype = parts[0].upper()
        if rtype in ('P','L','A','RC','CR','SQ','OB','OS','OC','OE'):
            layer.features.append(LayerFeature(fnum, rtype, parts[1:], {}))
            fnum += 1
        # else skip $,@,& sections for now (can be used to resolve symbol semantics)
    project.layers[layer_name] = layer
    return project

def parse_components_file(comp_file: str) -> List[Component]:
    """
    Parse comp_+_top/components and comp_+_bot/components.
    CMP records: index x y rot mirror net_num ... pkg_ref ordering references to PKG list order.
    See spec: CMP/TOP records and relation to PKG order. :contentReference[oaicite:9]{index=9} :contentReference[oaicite:10]{index=10}
    """
    comps = []
    if not os.path.exists(comp_file): return comps
    with open(comp_file, 'r', encoding='utf-8', errors='ignore') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#'): continue
            tok = ln.split()
            if tok[0].upper() == 'CMP':
                try:
                    idx = int(tok[1]); x=float(tok[2]); y=float(tok[3]); rot=float(tok[4])
                    side = tok[5] if len(tok)>5 else 'T'
                    # pkg_ref isn't always directly in same line; often comp file includes props; we set pkg_ref later if present
                    comp = Component(idx, f"cmp_{idx}", x,y,rot, 'N', pkg_ref=0, side=side)
                    comps.append(comp)
                except Exception:
                    continue
    return comps

# ------------ High level loader -----------
def load_odb_tree(root_path: str, step_name: Optional[str]=None) -> ODBProject:
    """
    root_path: product root (the folder that contains 'steps')
    step_name: optional, else picks first step found
    """
    proj = ODBProject(root_path)
    steps_dir = os.path.join(root_path, 'steps')
    if not os.path.isdir(steps_dir):
        raise FileNotFoundError("steps directory not found in ODB++ tree root")
    steps = [d for d in os.listdir(steps_dir) if os.path.isdir(os.path.join(steps_dir,d))]
    if not steps:
        raise FileNotFoundError("no steps found")
    step = step_name or steps[0]
    stepdir = os.path.join(steps_dir, step, 'eda')
    # parse eda/data
    eda_data = os.path.join(stepdir, 'data')
    if os.path.exists(eda_data):
        parse_eda_data(eda_data, proj)
    # parse layers (each layer dir inside stepdir, usually layers are under stepdir/<layername>/features)
    for entry in os.listdir(os.path.join(stepdir)):
        layer_path = os.path.join(stepdir, entry)
        if os.path.isdir(layer_path) and entry.startswith('layer_') or entry.startswith('top') or entry.startswith('bot') or entry.startswith('l'):
            # heuristic: treat as layer directory
            parse_layer_features(layer_path, entry, proj)
    # parse components
    comp_top = os.path.join(stepdir, 'comp_+_top', 'components')
    comp_bot = os.path.join(stepdir, 'comp_+_bot', 'components')
    proj.components_top = parse_components_file(comp_top)
    proj.components_bot = parse_components_file(comp_bot)
    return proj
