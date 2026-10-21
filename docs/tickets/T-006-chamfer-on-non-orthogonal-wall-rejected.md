# T-006: Chamfer on a non-orthogonal side wall rejected as oblique

Status: landed (lane/t006, 2026-10-21)
Opened: 2026-10-20 by the orchestrator, from an agy review (`.scratch/lanes/plan1-review23/REPORT.md`) whose finding was reproduced.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

`stl2scad/core/segmentation/defeature.py`, `_oblique` (about lines 69-73) and its use (about lines 152-154) reject a chamfer when the cap/side edge direction is within the cosine threshold of none of the extrusion axis or the two vectors of a single orthogonal `frame`. A prism whose walls are not at 90 degrees to each other has edges that match no frame vector, so a perfectly regular chamfer is refused with `("F6", "oblique edge")`.

Measured (`f2b.py`): a hexagonal prism, r=20, h=10, with a 45 degree, 2 mm top chamfer on one wall:

- hex with the chamfered wall at 0, 60 or 120 degrees: treatments `[]`, rejected `(('F6','oblique edge'),)`.
- square-prism control: `chamfer_1` 2.0 found.

This is a false negative: a legal chamfer falls back to plain faces.

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
`f2b.py`:

```python
from common import *
import math
H=10;c=2
def prism(n,R,ang,rot0=0):
    a=R*math.cos(math.pi/n)
    return f'''
difference(){{ rotate([0,0,{rot0}]) cylinder(r={R},h={H},$fn={n});
 rotate([0,0,{ang}]) rotate([90,0,0]) translate([0,0,-30]) linear_extrude(60)
   polygon([[{a-c},{H}],[{a+1},{H}],[{a+1},{H-c-1}]]);
}}'''
# control: square prism (walls normals at 0,90..) chamfer wall +x
for name,n,ang,r0 in [('ctrl_sq',4,0,45),('hex0',6,0,30),('hex60',6,60,30),('hex120',6,120,30),('hex90',6,90,30)]:
    m=render('f2b_'+name,prism(n,20,ang,r0))
    d=defeature(segment_mesh(m))
    sr=segment_mesh(m)
    print(name,'treat',[(t.id,round(t.size,3)) for t in d.treatments],'rejected',d.rejected)
    for f in d.result.faces:
        if hasattr(f.params,'normal') and abs(f.params.normal[2])<0.99: print('   wall',f.id,np.round(f.params.normal,3))
```

`f2b_hex0.scad` (the other variants differ in the chamfer cut angle):

```openscad

difference(){ rotate([0,0,30]) cylinder(r=20,h=10,$fn=6);
 rotate([0,0,0]) rotate([90,0,0]) translate([0,0,-30]) linear_extrude(60)
   polygon([[15.320508075688775,10],[18.320508075688775,10],[18.320508075688775,7]]);
}
```

## Rulings (2026-10-20)

- Keep the oblique guard for truly slanted edges. Reason: it exists to reject genuinely slanted edges. Rejected: removing the guard.
- Test the edge direction against the intersection line of its own two host faces (cap and side), not against one orthogonal frame for the whole part. Rejected: a single frame per part, which refuses regular chamfers on non-orthogonal walls.
- 2026-10-21: the 20 degree wall chamfer in the old oblique test is regular, so T-006 makes it legal. The old test now expects chamfer_1; test_genuinely_oblique_edge_still_rejected keeps the guard. Rejected: keeping the per-part frame rule.

## Settled design

`defeature.py`: `_oblique` and its use (about lines 152-154) compute, per chamfer candidate, the intersection direction of that candidate's host cap plane and host side plane, and compare the cap/side edge direction to it with the existing cosine threshold. The guard still returns `("F6", "oblique edge")` when the edge is not along that line. The per-part orthogonal `frame` is no longer used for this test.

## Owns

- `stl2scad/core/segmentation/defeature.py`
- `tests/data/segmentation/treatments_expected.json`
- the matching treatment test file under `tests/` (new test goes next to the existing treatment tests)

## Out of scope

Any other detector change, new primitive kinds, and weakening any existing treatment assertion.

## Acceptance

- [x] New test `test_chamfer_on_hexagonal_prism_wall_is_found`: the hexagonal-prism repro above (r=20, h=10, 2 mm chamfer), chamfered wall at 0 and 60 degrees, yields one `chamfer_1` of size 2.0 and no `oblique edge` rejection. Needs a new `treatments_expected.json` entry.
- [x] The 20 degree wall chamfer in the old oblique test is regular, so T-006 makes it legal and it now expects chamfer_1; test_genuinely_oblique_edge_still_rejected keeps the guard.
- [x] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [x] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [x] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
