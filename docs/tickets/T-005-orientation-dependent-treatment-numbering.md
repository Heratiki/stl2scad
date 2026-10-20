# T-005: Treatment numbering depends on part orientation

Status: open
Opened: 2026-10-20 by the orchestrator, from an agy review (`.scratch/lanes/plan1-review23/REPORT.md`) whose finding was reproduced.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

`stl2scad/core/segmentation/defeature.py`, `_side_frame` (about lines 64-65) picks the sign of the side basis vector `u` by `u[np.argmax(abs(u))] < 0` in world axes, and `order()` (about lines 184-194) sorts treatments by the dot products of the host side normal with that frame. The comment says the sign "chooses deterministic labels only", but the labels are customer-visible parameter names (`chamfer_1_width`). Rotating the same part by 180 degrees about Z swaps which chamfer is `chamfer_1`.

Measured with a 60x40x8 block with a 3 mm chamfer on one long top edge and a 2 mm chamfer on the opposite edge (`f1.py`):

- rotate [0,0,0]: chamfer_1 = 3.0 at y=-20, chamfer_2 = 2.0 at y=20.
- rotate [0,0,180]: chamfer_1 = 2.0, chamfer_2 = 3.0 (swapped).
- rotate [0,0,90]: chamfer_1 = 2.0 at x=-20.

The same part gets different parameter names depending on how it sits in the world frame, so a design edited in Customizer is not stable across re-exports of a rotated model.

Test gap: `tests/data/segmentation/treatments_expected.json` tests `chamfered_block` only at rotations [0,0,0] and [17,31,9], and with equal widths (`chamfer_1_width` 2, `chamfer_2_width` 2), so a swap cannot show.

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
`f1.py`:

```python
from common import *
for rot in ([0,0,0],[0,0,180],[0,0,90]):
    m=render('f1_%d'%rot[2], f'''
$fn=64;
rotate({rot}) translate([-30,-20,-4]) difference(){{ cube([60,40,8]);
 translate([-1,0,0]) rotate([90,0,90]) linear_extrude(62) polygon([[0,8],[3,8],[0,5]]);
 translate([-1,0,0]) rotate([90,0,90]) linear_extrude(62) polygon([[40,8],[38,8],[40,6]]);
}}''')
    d=defeature(segment_mesh(m))
    print(rot, 'axis',np.round(d.axis,3),'rejected',d.rejected)
    for t in d.treatments: print('  ',t.id,round(t.size,3),np.round(t.edge_point,2))
```

`f1_0.scad` (the [0,0,180] and [0,0,90] variants differ only in the `rotate()` argument):

```openscad

$fn=64;
rotate([0, 0, 0]) translate([-30,-20,-4]) difference(){ cube([60,40,8]);
 translate([-1,0,0]) rotate([90,0,90]) linear_extrude(62) polygon([[0,8],[3,8],[0,5]]);
 translate([-1,0,0]) rotate([90,0,90]) linear_extrude(62) polygon([[40,8],[38,8],[40,6]]);
}
```

## Confirm before implementing

Not a ruling. Suggested fix: anchor the basis sign to the part, for example from the offset of the side face from the mesh centroid, instead of to world axes. The maintainer must confirm this, and whether numbering should follow a part-intrinsic order at all.

## Rulings (2026-10-20)

None yet. No fix ruling exists for this ticket.

## Settled design

None until a ruling exists.

## Owns

- `stl2scad/core/segmentation/defeature.py`
- `tests/data/segmentation/treatments_expected.json`
- the matching treatment test file under `tests/` (new test goes next to the existing treatment tests)

## Out of scope

Any other detector change, new primitive kinds, and weakening any existing treatment assertion.

## Acceptance

- [ ] New test (in the treatment test file) `test_treatment_numbering_is_stable_under_180_rotation`: an unequal-width chamfered block (3 mm and 2 mm) at [0,0,0] and [0,0,180] yields the same `chamfer_N` id for the same physical chamfer. The block needs a new `treatments_expected.json` entry with unequal widths; the exact rule is whatever the maintainer rules.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged, including the existing `chamfered_block` entries.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
