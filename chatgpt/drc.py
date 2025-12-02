####################################################################################
# 4) drc.py

# Shapely 기반 DRC 엔진. 주요 기능:

# 전역 패드 수집(proj.pads) → STRtree 인덱스 생성

## 룰셋(JSON) 적용: min_spacing_all, min_spacing_diff_net, min_spacing_same_net 등
## NET 기반 검사: net_index 정보가 있을 경우 "same-net 예외" 처리 가능
## 결과 리포트 형태로 위반 항목 리스트 반환
####################################################################################

# drc.py
from shapely.strtree import STRtree
from shapely.geometry import Polygon, Point
from typing import List, Dict, Any, Tuple
import json
import math

"""
DRC engine:
 - build spatial index (STRtree) over pad polygons
 - for each pad, query neighbors and compute exact distances
 - apply rule set (default rules provided)
 - special handling for same-net pairs (can be allowed or lower-min spacing)

Rule format (json):
{
  "min_spacing_all": 0.006,
  "min_spacing_same_net": 0.0,
  "min_spacing_diff_net": 0.006,
  "per_net_overrides": {
      "GND": {"min_spacing_with_other": 0.003}
  }
}
"""

DEFAULT_RULES = {
    "min_spacing_all": 0.006,         # default minimum spacing for any two pads (units same as coordinates)
    "min_spacing_same_net": 0.0,      # allow touching for same net by default (common)
    "min_spacing_diff_net": 0.006,
    "per_net_overrides": {}
}

def load_rules_from_file(path:str) -> Dict[str,Any]:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # fill defaults
    for k,v in DEFAULT_RULES.items():
        if k not in data:
            data[k] = v
    return data

def _pair_allowed_by_net_rules(net_a_idx, net_b_idx, net_list, rules):
    """
    return effective minimum spacing between pads belonging to net_a and net_b
    """
    # if same net
    if net_a_idx is not None and net_b_idx is not None and net_a_idx == net_b_idx:
        return rules.get('min_spacing_same_net', 0.0)
    # different nets -> see if per_net_overrides exist
    # if either net name has override for spacing with others, use smallest allowed constraint
    base = rules.get('min_spacing_diff_net', rules.get('min_spacing_all', 0.0))
    # per-net override example: per_net_overrides: {"GND":{"min_spacing_with_other":0.003}}
    overrides = rules.get('per_net_overrides', {})
    net_a_name = net_list[net_a_idx].name if (net_a_idx is not None and net_a_idx >=0 and net_a_idx < len(net_list)) else None
    net_b_name = net_list[net_b_idx].name if (net_b_idx is not None and net_b_idx >=0 and net_b_idx < len(net_list)) else None
    mins = [base]
    if net_a_name and net_a_name in overrides:
        val = overrides[net_a_name].get('min_spacing_with_other')
        if val is not None: mins.append(val)
    if net_b_name and net_b_name in overrides:
        val = overrides[net_b_name].get('min_spacing_with_other')
        if val is not None: mins.append(val)
    return min(mins)

def run_drc(project, rules:Dict[str,Any]=None) -> List[Dict[str,Any]]:
    """
    Returns list of violation dicts:
    {'a_idx': int, 'b_idx': int, 'dist': float, 'a_info': {...}, 'b_info': {...}, 'req_min': float}
    """
    rules = rules or DEFAULT_RULES
    pads = project.pads  # list of dicts with 'poly', 'net_index', 'layer', 'feature'
    if not pads:
        return []
    polys = [p['poly'] for p in pads]
    tree = STRtree(polys)
    violations = []
    # To prevent duplicates we will enforce i<j
    for i, p in enumerate(pads):
        poly_i = p['poly']
        # query bbox-neighbors
        candidates = tree.query(poly_i)
        for cand in candidates:
            try:
                j = polys.index(cand)
            except ValueError:
                continue
            if j <= i:
                continue
            poly_j = pads[j]['poly']
            # exact distance
            d = poly_i.distance(poly_j)
            # get required min by net rules
            net_a = p.get('net_index', None)
            net_b = pads[j].get('net_index', None)
            req = _pair_allowed_by_net_rules(net_a, net_b, project.nets, rules)
            # fallback to global min_spacing_all if unspecified
            global_min = rules.get('min_spacing_all', 0.0)
            req = max(req, global_min) if req is not None else global_min
            if d < req - 1e-12:
                violations.append({
                    'a_idx': i,
                    'b_idx': j,
                    'dist': d,
                    'required': req,
                    'a': {'layer': p.get('layer'), 'fid': p.get('fid'), 'net_index': net_a},
                    'b': {'layer': pads[j].get('layer'), 'fid': pads[j].get('fid'), 'net_index': net_b}
                })
    return violations

# Utility to pretty-print violations
def print_violations(violations, project):
    for v in violations:
        a = v['a']; b = v['b']
        net_a = project.nets[a['net_index']].name if (a['net_index'] is not None and a['net_index']>=0) else 'UNKNOWN'
        net_b = project.nets[b['net_index']].name if (b['net_index'] is not None and b['net_index']>=0) else 'UNKNOWN'
        print(f"Violation: pad {v['a_idx']} (net:{net_a}, fid:{a['fid']}) <-> pad {v['b_idx']} (net:{net_b}, fid:{b['fid']}), dist={v['dist']:.6f}, required={v['required']:.6f}")
