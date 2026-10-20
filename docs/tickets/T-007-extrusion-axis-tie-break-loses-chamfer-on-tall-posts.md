# T-007: Wrong extrusion axis on tall posts loses the chamfer

Status: landed (worktree-agent-a1a03d31d1797fba7, 2026-10-20)
Opened: 2026-10-20 by the orchestrator, from an agy review (`.scratch/lanes/plan1-review23/REPORT.md`) whose finding was reproduced.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

`stl2scad/core/segmentation/regularize.py`, `extrusion_axis` (about lines 295-307) scores candidate axes by unexplained face area. Candidates within 1 % of the total area of the minimum are "tied", and the tie is broken by the largest cap area (`max(tied, key=lambda i: scores[i][1])`). A tall post has big side faces, so a side-to-side axis wins the tie over the true long axis. Downstream, `defeature` then sees the chamfer face as parallel-ish to the chosen axis and skips it.

Measured (`f3.py`), a block with a 2 mm chamfer cut across one top edge:

- (20,20,100): axis [0,-1,0], treatments `[]` (chamfer missed).
- (20,20,30): same, chamfer missed.
- (20,20,10): axis Z, chamfer found.
- (20,30,100): axis X, chamfer found.

False negative: the output depends on the part's aspect ratio.

The standing maintainer rule (2026-10-20) is to ticket every detector false positive or primitive issue; the maintainer may set `wontfix` later. The repro files live in a temporary scratch directory, so the scripts are copied here. `common.py` (shared helper, used by every repro):

```python
import sys, subprocess, numpy as np
sys.path.insert(0,'/home/heratiki/Source/stl2scad')
from stl.mesh import Mesh
from stl2scad.core.segmentation import segment_mesh
from stl2scad.core.segmentation.defeature import defeature
from stl2scad.core.segmentation.regularize import regularize, extrusion_axis
import os
D=os.path.dirname(os.path.abspath(__file__))
def render(name, scad):
    p=f'{D}/{name}.scad'; open(p,'w').write(scad)
    s=f'{D}/{name}.stl'
    subprocess.run(['openscad','--render','-o',s,p],check=True,capture_output=True)
    return Mesh.from_file(s)
```
`f3.py`:

```python
from common import *
def col(w,l,h,c=2):
    return f'''
difference(){{ translate([-{w/2},-{l/2},0]) cube([{w},{l},{h}]);
 translate([{w/2},0,{h}]) rotate([90,0,0]) translate([0,0,-{l}]) linear_extrude({2*l}) polygon([[-{c},0],[1,0],[1,-{c+1}]]) ;
}}'''
for (w,l,h) in [(20,20,100),(20,20,30),(20,20,10),(20,30,100)]:
  for tag,sc in [('chamf',col(w,l,h)),('plain',f'translate([-{w/2},-{l/2},0]) cube([{w},{l},{h}]);')]:
    m=render(f'f3_{w}_{l}_{h}_{tag}',sc)
    r=segment_mesh(m); fr=regularize(r); ax=extrusion_axis(fr)
    d=defeature(r)
    print((w,l,h),tag,'axis',np.round(ax,3),'treat',[(t.id,round(t.size,2)) for t in d.treatments],'rej',d.rejected)
```

`f3_20_20_100_chamf.scad`:

```openscad

difference(){ translate([-10.0,-10.0,0]) cube([20,20,100]);
 translate([10.0,0,100]) rotate([90,0,0]) translate([0,0,-20]) linear_extrude(40) polygon([[-2,0],[1,0],[1,-3]]) ;
}
```

## Rulings (2026-10-20)

- In an extrusion-axis tie, prefer the axis that explains more treatments, then the larger cap area. Reason: a chamfer must not be lost to an aspect-ratio accident. Rejected: cap area alone.
- Keep the 1 % tie band. Reason: it keeps plain-part axes unchanged. Rejected: widening or removing the band.

## Settled design

`regularize.py`, `extrusion_axis` (about lines 295-307): among the candidates within 1 % of the total area of the minimum score, choose by (a) the number of planar treatments (chamfer bisector plus convex edge perpendicular to the candidate axis) the axis explains, then (b) the largest cap area. The 1 % band is unchanged. `defeature.py` changes only if the treatment count needs a helper there.

## Owns

- `stl2scad/core/segmentation/regularize.py`
- `stl2scad/core/segmentation/defeature.py` (only if the ruling needs it)
- `tests/data/segmentation/treatments_expected.json`
- the matching treatment test file under `tests/` (new test goes next to the existing treatment tests)

## Out of scope

Any other detector change, new primitive kinds, and weakening any existing treatment assertion.

## Acceptance

- [ ] New test `test_tall_post_chamfer_is_found`: the (20,20,100) and (20,20,30) repros above each yield one chamfer of size 2.0.
- [ ] New test `test_extrusion_axis_unchanged_for_plain_posts`: the plain (no chamfer) blocks keep the axis they get today, so only chamfered parts change. Existing axis expectations stay unchanged.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
