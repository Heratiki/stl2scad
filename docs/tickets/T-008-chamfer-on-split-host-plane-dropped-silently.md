# T-008: Chamfer whose host wall is split by a slot is dropped without a reason

Status: landed (lane/t008, 2026-10-21)
Opened: 2026-10-20 by the orchestrator, from an agy review (`.scratch/lanes/plan1-review23/REPORT.md`) whose finding was reproduced.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

`stl2scad/core/segmentation/defeature.py` (about lines 149-150): after `_host_pairs(...)`, `if len(pairs) != 1: continue` drops the candidate with no entry in `rejected`. When a slot splits the host side plane into two coplanar faces, the chamfer gets two (cap, side) pairs and vanishes silently.

Measured (`f5b.py`, spying on `_host_pairs`), a 60x40x8 block with a top-edge chamfer, with and without a slot cut into the front wall:

- no slot: pairs `[('F2','F0')]`, treatments 1.
- slot: pairs `[('F3','F0'),('F3','F5')]`, treatments 0, rejected `()`.

Two faults: a false negative, and the missing rejection reason, which breaks the diagnostic contract (every dropped candidate has a reason).

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
`f5.py` supplies the `blk` helper (`f5b.py` imports it):

```python
from common import *
def blk(slot, chamfer=True):
    s='difference(){ cube([60,40,8]);\n'
    if chamfer: s+=' translate([-1,0,0]) rotate([90,0,90]) linear_extrude(62) polygon([[0,8],[3,8],[0,5]]);\n'
    if slot: s+=' translate([25,-1,-1]) cube([10,15,6]);\n'  # through-slot in front wall (blind pocket from front, below top)
    return s+'}'
if __name__=="__main__":
 for tag,slot,ch in [('noslot',False,True),('slot_lowerwall',True,True),('slot_nochamfer',True,False)]:
     r=segment_mesh(render('f5_'+tag,blk(slot,ch))); d=defeature(r)
     print(tag,'treat',[(t.id,t.hosts,round(t.size,2)) for t in d.treatments],'rej',d.rejected)
     print('  front-ish planes',[(f.id,np.round(f.params.normal,2).tolist()) for f in d.result.faces if hasattr(f.params,'normal') and f.params.normal[1]<-0.5])
     print('  all faces',[f.id for f in r.faces])
```

`f5b.py`:

```python
from common import *
import stl2scad.core.segmentation.defeature as df
orig=df._host_pairs
def spy(res,face,*a):
    p=orig(res,face,*a)
    if isinstance(face.params,df.Plane) and abs(face.params.normal[2])<0.99 and abs(face.params.normal[2])>0.05:
        print('  chamfer',face.id,'pairs',[(c.id,s.id) for c,s,_,_ in p])
    return p
df._host_pairs=spy
from f5 import blk
for tag,slot in [('noslot',False),('slot',True)]:
    print(tag); d=defeature(segment_mesh(render('f5b_'+tag,blk(slot)))); print('  treat',len(d.treatments),'rej',d.rejected)
```

`f5b_slot.scad`:

```openscad
difference(){ cube([60,40,8]);
 translate([-1,0,0]) rotate([90,0,90]) linear_extrude(62) polygon([[0,8],[3,8],[0,5]]);
 translate([25,-1,-1]) cube([10,15,6]);
}
```

## Rulings (2026-10-20)

- Merge coplanar host faces before pairing. Reason: a slot splits one wall into coplanar faces; they are one host. Rejected: dropping the candidate when `len(pairs) != 1`.
- Every dropped candidate always gets a `rejected` entry with a reason. Reason: the diagnostic contract. Rejected: silent `continue`.

## Settled design

`defeature.py` (about lines 149-150): coplanar host faces are merged before `_host_pairs(...)` pairing, so the slot repro yields one (cap, side) pair and one chamfer of the same size as the no-slot block. Where `len(pairs) != 1` still holds after merging, or any other path drops a chamfer candidate, append a `rejected` entry with a named reason instead of `continue`.

## Owns

- `stl2scad/core/segmentation/defeature.py`
- `tests/data/segmentation/treatments_expected.json`
- the matching treatment test file under `tests/` (new test goes next to the existing treatment tests)

## Out of scope

Any other detector change, new primitive kinds, and weakening any existing treatment assertion.

## Acceptance

- [x] New test `test_chamfer_with_slotted_host_wall_is_found`: the slot repro (`f5b_slot.scad`) yields one chamfer, the same size as the no-slot block.
- [x] New test `test_dropped_chamfer_candidate_records_a_reason`: any chamfer candidate not turned into a treatment appears in `rejected` with a reason; asserts that no candidate is dropped without a reason (checked for a case that stays unsupported).
- [x] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [x] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [x] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
