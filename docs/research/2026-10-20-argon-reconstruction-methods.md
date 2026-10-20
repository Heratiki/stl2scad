# Research Report: Mesh-to-Parametric-CAD Reconstruction Methods

## Executive Summary (<= 20 lines)
- **Verdict on A (Methodology):** Surface segmentation + face graph ([`pipeline.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py)) is the right foundation, but **flat single-pass feature rules ([`features.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py)) and single-cap extrusion ([`sections.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/sections.py)) are not**. Replace step 4 with **(A1) Iterative Defeaturing ("Suppress-and-Extend" graph rewriting, `fits now`)** + **(A2) Multi-Height 2.5D Slab Slicing (`fits now`)**, plus **(A4) Constrained Global Fitting (`fits now`)**.
- **Ranked Options for B (Unresolved Regions by Editability/Effort):**
  1. **Conic/Ellipse & G1-Biarc Profile Primitives (`fits now`):** Highest ROI — empirically, `memo_cartridge` feet (`C120–C125`) are **exact quarter-ellipses** ($a=3.0, b=8.0\text{ mm}$, max error $0.000008\text{ mm}$), not free-form splines or 6 circular arcs!
  2. **Parametric 2D Cubic Bézier / Catmull-Rom Sketch Curves (`fits now`):** 4–6 control-point sliders evaluated in pure SCAD.
  3. **Host-Anchored & Radius-Scaled Hybrid Polyhedron Patch (`fits now`):** Translates/scales with host face & adjacent round sliders.
  4. **Cross-Sectional Multi-Profile Loft (`fits with effort`):** Slicing along a spine into parameterized SCAD skin loops.
  5. **Dual-Mode Analytic Proxy (`hull()`/`sphere()`) with Gate Toggle (`fits with effort`):** Exact patch by default, parametric proxy on edit.
  6. **Bicubic Tensor-Product B-Spline Surface Grid in SCAD (`fits with effort`):** NURBS control net evaluated to `polyhedron`.
  7. **Interactive / Sidecar Hint Disambiguation (`fits with effort`):** User/JSON override for ambiguous regions.
- **Top Recommendations for Specific Questions (1–5):**
  - **Q1 (Irregular Arcs):** Drop `len(unique) != 2` in [`coarse.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L97) for 2D line-collinearity + Taubin/Gauss-Newton fit (`fits now`); use **Runs Test + Menger curvature + BIC conic test (`fits now`)** to separate arcs from ellipses/splines.
  - **Q2 (Rounds/Chamfers/Partial Arcs):** Recognize rounds/chamfers in the RAG, **extend host planes to the virtual sharp corner**, and emit via **2D profile arc** or **3D negative wedge cutter** (`fits now`).
  - **Q3 (Hybrid Output):** Close open free-form patches into watertight sub-solids by **projecting boundary loops onto extended adjacent host planes** (with `_join_epsilon` overlap) and anchor to host expressions (`fits now`).
  - **Q4 (Threads/Holes):** Detect coaxial cone/cylinder chains in RAG for counterbores/countersinks (`fits now`), axial pitch-FFT for threads (`fits with effort`), and emit **dual-mode `exact_mesh_geometry` toggle + helical sweep** to pass the $0.05\text{ mm}$ gate (`fits now`).
  - **Q5 (Overall Method):** Combine **Várady/Benkő suppress-and-extend + Point2CAD analytic face intersection + 2.5D slab slicing (`fits now`)**; skip GPU neural networks (`does not fit`).

---

## Empirical Discovery on the Target Real Parts (Read First)

Before evaluating abstract methods, we ran direct geometric diagnostics on the two stand-in real parts that currently block the pipeline in [`2026-10-20-edge-rounds-design.md`](file:///home/heratiki/Source/stl2scad/docs/superpowers/specs/2026-10-20-edge-rounds-design.md) and [`segmentation_real_parts.md`](file:///home/heratiki/Source/stl2scad/docs/planning/segmentation_real_parts.md):

1. **`memo_cartridge` (`MEMO BOY - CARTRIDGE.STL`, 1534 triangles, bbox diagonal $116.89\text{ mm}$):**
   - **Open Hand-Check #3 Answered ("Are the foot outlines true arcs or a spline?"):** Neither! We extracted the 25 top-cap vertices ($z = 6.563\text{ mm}$) of the left foot's curved outer profile (`C120, C121, C122, P111, P112`, $x \in [24.925, 27.925]$, $y \in [10.610, 18.610]$) and the symmetric right foot (`C123, C124, C125, P113, P114`, $x \in [57.925, 60.925]$, $y \in [10.610, 18.610]$).
     - The discrete Menger circumradius along the 25 consecutive vertices drops **strictly monotonically at every single vertex** from $R = 20.992\text{ mm}$ at $(27.909, 11.437)$ down to $R = 1.135\text{ mm}$ at $(25.019, 18.606)$.
     - Why did [`survey_real_parts.py`](file:///home/heratiki/Source/stl2scad/scripts/survey_real_parts.py) `draft` report six circular arcs `C120–C125` with radii $2.27\text{ mm}$, $5.93\text{ mm}$, and $15.97\text{ mm}$? Because its greedy circle fitter broke a continuous variable-curvature curve into three piecewise circle approximations with high residuals ($\varepsilon_{\max} = 0.0400\text{ mm}$ on `C120` and $0.0202\text{ mm}$ on `C122` — **1000× larger** than the $0.000001\text{ mm}$ residuals on true circular arcs `C116/C117`).
     - Testing an **exact axis-aligned quarter-ellipse** $\left(\frac{x - x_0}{3.0}\right)^2 + \left(\frac{y - y_0}{8.0}\right)^2 = 1$ with semi-axes $a = 3.00000\text{ mm}$, $b = 8.00000\text{ mm}$ (theoretical curvature radii $\kappa^{-1} \in [a^2/b, b^2/a] = [1.125\text{ mm}, 21.333\text{ mm}]$) centered at $(24.925, 10.610)$ and $(60.925, 10.610)$ yields a **maximum geometric error of $0.000008\text{ mm}$ ($8\text{ nm}$, pure IEEE-754 float32 rounding)** across all 25 vertices!
   - **What are the other ~500 unfitted facet planes on the `memo_cartridge` feet?**
     - Faces `P61..P76` (left foot) and `P86..P101` (right foot) have normals in the YZ plane ($n_x = 0$) and lie on an **exact $R = 3.00000\text{ mm}$ horizontal cylinder along X** centered at $(y, z) = (15.9674, 4.563)$ with **max residual $0.000005\text{ mm}$**. Both [`segment_mesh`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L249) and `draft` missed them because one end of each horizontal strip is obliquely clipped by the elliptical side wall (so triangles do not project to 2 points along X, failing [`coarse.py:97`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L97)).
     - Faces `P77..P85` (left foot) and `P102..P110` (right foot) have normals in the XY plane ($n_z = 0$) and lie on an **exact $R = 3.00000\text{ mm}$ vertical cylinder along Z** centered at $(15.625, 15.9674)$ and $(70.225, 15.9674)$ with **max residual $0.000005\text{ mm}$**, clipped at the bottom ($z = 3.96\text{ mm}$) by a 45° chamfer (`P58`/`P60`).
     - Only the two 3D corner blends (`F118` and `F119`, 367 triangles / $9.22\text{ mm}^2$ each, totaling **$0.13\%$ of total part area**) where the $R=3$ X-round, $R=3$ Z-round, and 45° chamfers (`P57, P58, P59, P60`) meet are genuinely non-cylindrical setback corner blends.

2. **`memo_power_button` (`MEMO BOY - BUTTON - POWER.STL`, 3568 triangles, bbox diagonal $30.82\text{ mm}$):**
   - **Open Hand-Check #4 Answered ("Is the unfitted head side a cylinder about Y?"):** Partially — it is a **compound dressed edge** consisting of:
     - Two **exact $R = 1.0000\text{ mm}$ vertical Z-cylinders** (`P14..P49` plus 144 vertical-normal triangles in `F56`, centered at $(87.4254, 12.010)$ and $(87.4254, 14.010)$, max residual $0.0005\text{ mm}$), which were missed because their top and bottom ends are obliquely clipped by 45° chamfers `P12` and `P13` ($n = [0.707, 0, \pm 0.707]$).
     - Two **exact $R = 2.00000\text{ mm}$ horizontal Y-cylinders** (88 triangles in `F56` with $n_y = 0$, centered at $(x, z) = (86.425, 89.8272)$ and $(86.425, 96.1704)$, **max residual $0.000006\text{ mm}$**), also clipped by the 45° chamfers `P12` and `P13`.
     - Four 3D corner blends (2568 triangles in `F56`, $3.4\%$ of total surface area) where the $R=1$ Z-rounds roll over the $R=2$ Y-rounds and 45° chamfers.

---

## Section A: Challenging the Methodology — Is Ours the Most Capable One?

### Critique of the Current Pipeline ([`stl2scad/core/segmentation/`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/))

The current architecture in [`pipeline.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py), [`features.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py), and [`sections.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/sections.py) is a strict, feed-forward 5-stage pipeline:
1. **Stage 1–2 (Bottom-up greedy segmentation):** [`_plane_patches`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L30) grows coplanar regions ($\Delta\theta \le 0.25^\circ$); [`_extract_cylinders`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L94) runs 3-patch RANSAC on smooth components; [`extract_coarse`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L55) groups rectangular facet strips; everything left over is dumped back into individual planar faces ([`pipeline.py:276-281`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L276-L281)).
2. **Stage 3 (Region Adjacency Graph):** [`_region_graph`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L182) labels boundaries `convex`, `concave`, or `tangent` ($\le 7.5^\circ$).
3. **Stage 4 (One-shot whole-graph feature classification):** Either [`detect_pin`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pins.py#L10), [`detect_section_features`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/sections.py#L162) (requiring every side face to span a single pair of parallel end caps), or [`_cylinder_features`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py#L245) + [`_cap_pair`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py#L377) must explain **100% of the faces in one pass**.

#### Why this architecture stalls on real parts (3 structural flaws)
1. **No Defeaturing / Graph-Reduction Loop ("Dress-up blindness"):** In mechanical CAD, fillets, rounds, and chamfers are applied *last* on top of sharp B-rep edges, clipping the underlying planar and cylindrical faces and destroying their cap-to-cap adjacency. Because [`features.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py) tries to recognize the base extrusion *while dress-up features are still present in the graph*, every new interaction (a fillet lip, a chamfer clipping a profile arc, a round meeting a chamfer) breaks cap loop reconstruction ([`_boundary_loop`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py#L102)) and requires fragile combinatorial special cases (like lines 257–298 of [`features.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py#L257-L298)).
2. **Single-Cap Extrusion Assumption vs. Multi-Height (2.5D) Parts:** Both `memo_cartridge` (a $2\text{ mm}$ plate in $Y \in [6.61, 8.61]$ united with two $12\text{ mm}$ feet in $Y \in [6.61, 18.61]$) and `memo_power_button` (a $2\text{ mm}$ bar in $Z \in [88, 90]$, a $10\text{ mm}$ head in $Z \in [88, 98]$, and a $10\text{ mm}$ rib in $Z \in [88, 98]$) are **multi-height stepped extrusions**, not a single profile extruded between two caps. [`_cap_pair`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py#L377) and [`sections.py:187`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/sections.py#L187) fundamentally cannot represent multi-height extrusions.
3. **3D Surface Segmentation Before 2D Slicing:** Recovering 2D profile arcs by first segmenting 3D cylinder strips (`coarse.py`) fails whenever a 3D chamfer or fillet clips one end of the cylinder strip (`len(unique) != 2`). Slicing the mesh with a 2D plane mid-way through an extrusion slab recovers clean 2D polygons and arcs directly, immune to 3D end-clipping.

---

### Evaluation of Alternative & Complementary Methodologies

| Methodology | Primary Sources | What It Does Better Than Ours | What It Does Worse Than Ours | Role in `stl2scad` & Verdict |
|---|---|---|---|---|
| **A1. Iterative Defeaturing & Analytic Face Extension ("Suppress-and-Extend" B-Rep Rewriting)** | Várady, Martin & Cox (1997) ([DOI](https://doi.org/10.1016/S0010-4485(96)00054-1)); Benkő, Martin & Várady (2001) ([DOI](https://doi.org/10.1016/S0010-4485(00)00139-1)); Kós, Martin & Várady (2000) ([DOI](https://doi.org/10.1016/S0167-8396(99)00061-8)); Venkataraman et al. (2002) ([DOI](https://doi.org/10.1145/566282.566301)) | Strips away chamfers, rounds, corner blends, bosses, and pockets **iteratively**, extending adjacent analytic faces to restore sharp B-rep edges and intact cap loops before base-body detection. Eliminates combinatorial interaction rules. | Requires an analytic surface-intersection / face-extension step in the RAG rather than reading raw mesh boundary loops directly. | **Replaces Step 4's flat dispatch (`fits now`)**. Pure numpy/networkx; directly solves `memo_cartridge` and `memo_power_button` dress-up clipping. |
| **A2. Multi-Height 2.5D Change-Point Slab Slicing (Sketch-and-Extrude by Slicing)** | Classical 2.5D feature recognition / Reeb-graph slicing; Uy et al., *Point2Cyl* (CVPR 2022, [arXiv:2112.09329](https://arxiv.org/abs/2112.09329)); Ren et al., *ExtrudeNet* (ECCV 2022, [arXiv:2209.15632](https://arxiv.org/abs/2209.15632)) | Finds discrete height levels along dominant axes ($z_0 < z_1 < \dots < z_k$), slices the mesh at slab midpoints to get exact 2D cross-sections (bypassing 3D end-clipping), and merges slabs into stepped extrusions (`union`/`difference` of `linear_extrude`). | Purely 2.5D per axis; 3D edge rounds/chamfers perpendicular to the slice axis must either be defeatured first (via A1) or detected as cross-section change-of-width across slices. | **Replaces single-cap [`_cap_pair`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py#L377) & generalizes [`sections.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/sections.py) (`fits now`)**. Needed for Goal 7 (stepped extrusions). |
| **A3. Half-Space Cell Complex + Inverse CSG Synthesis + E-Graph Equality Saturation** | Shapiro & Vossler (1991) ([DOI](https://doi.org/10.1145/102756.102759)); Du et al., *InverseCSG* (SIGGRAPH Asia 2018, [DOI](https://doi.org/10.1145/3272127.3275006)); Nandi et al., *Szalinski* (PLDI 2020, [arXiv:2001.10633](https://arxiv.org/abs/2001.10633)) | Guarantees a valid Boolean CSG tree for **any** combination of overlapping positive/negative primitives (solving arbitrary polarity & nested containment), and folds repeated CSG subtrees into parametric loops/modules via e-graphs. | Arrangement size grows as $O(N^3)$ in the number of planes/cylinders; produces raw CSG trees whose parameters are not automatically host-relative unless paired with a constraint graph; *InverseCSG* uses Sketch solver (slow). | **Replaces/augments boolean polarity assembly in Step 4 and refactors IR in Step 5 (`fits with effort`)**. A bounded cell-classification solver for $\le 30$ primitives in numpy is fast and eliminates polarity heuristics. |
| **A4. Constrained Fitting & Regularity Solver ("Beautification")** | Benkő, Kós, Várady, Andor & Martin (2002) ([DOI](https://doi.org/10.1016/S0167-8396(02)00083-3)); Li et al., *GlobFit* (SIGGRAPH 2011, [DOI](https://doi.org/10.1145/1964921.1964947)) | Enforces exact orthogonality ($\mathbf{n}_i \perp \mathbf{n}_j$), parallelism, coaxiality, equal radii, and cylinder-plane tangency ($\|\mathbf{c} - \mathbf{p}\| = R$) across all fitted primitives simultaneously via SQP / Lagrange multipliers. Prevents micrometre gaps in CSG! | Adds a small global optimization solve ($\sim 5\text{–}20\text{ ms}$ in `scipy.optimize` or Gauss-Newton) after segmentation. | **Augments Steps 2–3 (`fits now`)**. Eliminates float32 normal drift (e.g. `C121` axis `[0.0165, -0.0359, 0.9992]` in `memo_cartridge`). |
| **A5. Medial Axis / Skeletal & Generalized Cylinder Decomposition** | Tagliasacchi et al. (2016) ([DOI](https://doi.org/10.1111/cgf.12865)); Li et al., *Q-MAT* (SIGGRAPH 2015, [DOI](https://doi.org/10.1145/2766977)); Blum (1967) | Directly recovers **wall thickness** ($t = 2r_{\text{medial}}$) and **centerline spine** for thin ribs (`memo_power_button` 1 mm fin), shells, bent clips (`Mounted Clip.stl`), and swept ducts (`HMG6` fan ducts). | Interior 3D Voronoi / medial axis on raw STL meshes is sensitive to surface noise unless simplified (Q-MAT); overkill for simple plates. | **Complements Step 4 in 2D (for profiles/ribs, `fits now`) and 3D (for shells/ducts, `fits with effort`)**. In 2D sections, medial axis of a polygon trivially identifies ribs, U/T/L webs, and slot centerlines! |
| **A6. Differentiable Rendering / Neural SDF Sketch-Extrude Optimization** | Li et al., *SECAD-Net* (CVPR 2023, [arXiv:2303.10613](https://arxiv.org/abs/2303.10613)); Yu et al., *CAPRI-Net* (CVPR 2022, [arXiv:2104.05652](https://arxiv.org/abs/2104.05652)); Kania et al., *UCSG-Net* ([arXiv:2004.09952](https://arxiv.org/abs/2004.09952)) | Can parse noisy scans without sharp creases into approximate sketch-extrude or quadric CSG assemblies without hand-coded topological rules. | Smooth SDF relaxation blurs sharp corners ($> 0.2\text{ mm}$ error, failing the $0.05\text{ mm}$ Hausdorff gate), requires PyTorch/GPU, non-deterministic, and produces unlabelled implicit sketches. | **Does not fit (`does not fit`)** the deterministic, CPU-only, $0.05\text{ mm}$-gated pipeline. |
| **A7. LLM/VLM Program Search with Geometric Verifier (CEGIS Loop)** | Rukhovich et al., *CAD-Recode* ([arXiv:2412.14042](https://arxiv.org/abs/2412.14042)); Khan et al., *CAD-SIGNet* (CVPR 2024, [arXiv:2402.17678](https://arxiv.org/abs/2402.17678)) | Generates idiomatic, human-readable parametric CAD code (loops, semantic variable names, macros) and can iteratively refine parameters using Hausdorff/IoU feedback. | Requires a 1.5B+ parameter neural model or API call; non-deterministic; hallucinates coordinates without geometric segmentation anchoring. | **Core runtime: `does not fit`**. **Offline corpus / improvement loop (`stl2scad/improvement_loop/`): `fits with effort`** as a synthesizer over the segmented RAG! |

### Concrete Architectural Blueprint for `stl2scad` (Combining A1 + A2 + A4)

Instead of replacing [`segment_mesh`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L249), evolve Step 3–4 from a flat matcher into a **3-Stage Defeature-Slice-Replay Pipeline**:
1. **Constrained Regularization (A4):** After `segment_mesh`, snap near-parallel/orthogonal plane normals and cylinder axes ($\le 1^\circ$) to exact part-frame axes and enforce tangency offsets.
2. **Iterative Defeaturing Pass (A1):** In the Region Adjacency Graph, identify leaf dress-up faces in topological order:
   - *Pass 1a (3D Corner Blends):* Small free-form/toroidal/spherical patches bounded by rounds/chamfers (`F118, F119` in `memo_cartridge`, `F56` corners in `memo_power_button`). Record and remove them from the graph.
   - *Pass 1b (3D Edge Rounds & Chamfers):* Cylinder strips (`convex` or `concave`) and narrow bevel planes between two host faces. Record them as edge-treatment operations, remove their faces from the RAG, and **analytically intersect the extended host planes** to restore the virtual sharp edge.
   - *Pass 1c (Bosses, Blind Holes, Pockets, Counterbores):* Coaxial cylinder/cone chains terminating in a cap on a host face. Record and remove from the host face.
3. **Multi-Height 2.5D Slab Slicing (A2):** On the defeatured graph (or by slicing the mesh at the remaining planar cap heights $z_0 < z_1 < \dots < z_k$), extract the 2D profile (with line, circular arc, and elliptical arc segments) for each height slab, unify adjacent slabs into stepped extrusions, and replay the recorded bosses, holes, chamfers, rounds, and remainder patches in `to_ir.py`.

---

## Section B: Handling Regions That Do Not Resolve (Ranked by Editability per Unit Effort)

When a surface region is not explained by planes or circular cylinders, dumping it into a static `polyhedron()` loses parametric editability. Below are **seven alternatives**, ranked from highest to lowest **editability gained per unit of implementation effort** in [`stl2scad/core/segmentation/`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/).

| Rank | Method | Editability Gained | Implementation Effort | Fit Verdict | Best Target in `stl2scad` |
|---|---|---|---|---|---|
| **1** | **Extended Analytic & Conic Profile Primitives (2D Ellipses, G1 Biarcs, Cones, Tori)** | **Very High** (2 clean sliders, e.g. `rx`, `ry` or `r1`, `r2`; exact geometry) | **Low** (~80 LOC in `fitting.py` + `section_emit.py`) | **`fits now`** | `memo_cartridge` feet (`C120–C125` = exact $3\times 8\text{ mm}$ quarter-ellipses!) |
| **2** | **2D Parametric Cubic Bézier / Catmull-Rom Spline Sketch Segments (`SketchSpline2D`)** | **High** (4–6 control/knot point sliders in Customizer; smooth curve) | **Low–Medium** (~120 LOC least-squares Bezier fit + 6-line SCAD function) | **`fits now`** | Free-form 2D extrusion outlines that fail circle & ellipse fits |
| **3** | **Host-Anchored & Proportionally Scaled Hybrid Polyhedron Patch** | **Medium** (patch moves automatically with host wall/thickness and scales with adjacent round radius) | **Low** (~60 LOC in `to_ir.py` & `emit.py`) | **`fits now`** | 3D corner blends (`F118/F119` in `memo_cartridge`, `F56` in `memo_power_button`) |
| **4** | **Cross-Sectional Loft / Skin Between Recovered 2D Sections** | **High** (editable section widths, heights, and spine offsets in SCAD) | **Medium** (~200 LOC section slicer + SCAD skin list comprehension) | **`fits with effort`** | Swept ducts (`HMG6` fan ducts), tapered legs, ergonomic handles |
| **5** | **Dual-Mode Analytic Proxy (`hull()` / Sphere / Torus) with Gate-Preserving Toggle** | **Medium–High** (exact mesh at default `exact_patch=true`; full parametric solid when edited) | **Medium** (~150 LOC proxy fitter + conditional SCAD emit) | **`fits with effort`** | Setback vertex blends & complex variable-radius rounds |
| **6** | **Bicubic Tensor-Product B-Spline Surface Fit Emitted as a SCAD Evaluator Grid** | **Medium** ($4\times 4$ control-point Z/offset sliders in Customizer) | **High** (~350 LOC UV parameterization + LSQ B-spline + SCAD evaluator) | **`fits with effort`** | Sculpted free-form caps (`memo_power_button` head if modeled as a single surface) |
| **7** | **Interactive / Sidecar Hint Disambiguation (`--hints` JSON or GUI prompt)** | **High when used** (user picks semantic intent or supplies formula) | **Low–Medium** (~100 LOC schema hook), but breaks zero-touch batch flow | **`fits with effort`** | Ambiguous local corpus parts (`stl2scad/tuning/local_corpus.py`) |

### Deep Dive on the Top 4 Ranked Methods for B

#### 1. Conic / Elliptical & G1-Biarc Profile Primitives (`fits now`)
- **How it works:** When a 2D section curve or 3D cylindrical strip fails constant-radius circle fitting, test:
  1. **Direct Least-Squares Ellipse Fit** (Fitzgibbon, Pilu & Fisher 1999, *"Direct least square fitting of ellipses"*, *IEEE TPAMI* 21(5):476–480, [DOI:10.1109/34.765658](https://doi.org/10.1109/34.765658)): solves a $6\times 6$ generalized eigensystem with constraint $4AC - B^2 = 1$ in $< 0.2\text{ ms}$, followed by 3 Gauss-Newton steps on orthogonal distance.
  2. **Optimal G1 Piecewise Biarc Fit** (Piegl & Tiller 2002, [DOI:10.1016/S0010-4485(01)00160-9](https://doi.org/10.1016/S0010-4485(01)00160-9)): fits two tangent-continuous circular arcs matching endpoint tangents.
- **OpenSCAD Emission:** An elliptical arc with semi-axes `a = arc_1_rx`, `b = arc_1_ry` is emitted in [`section_emit.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/section_emit.py) using a 1-line helper:
  ```openscad
  function _ellipse_arc(c, rx, ry, a0, sweep, n) =
      [for (i=[0:n]) let(t = a0 + sweep*i/n) c + [rx*cos(t), ry*sin(t)]];
  ```
- **Why it ranks #1:** It turns the 570-triangle `memo_cartridge` foot problem from an "unresolvable spline or 6 messy arcs" into **two exact design parameters (`foot_corner_rx = 3`, `foot_corner_ry = 8`)** with $0.000008\text{ mm}$ error.

#### 2. Parametric 2D Cubic Bézier / Interpolating Catmull-Rom Curves (`fits now`)
- **How it works:** If a 2D boundary curve exceeds the ellipse residual gate, fit a sequence of cubic Bézier segments (Schneider 1990, *"An Algorithm for Automatically Fitting Digitized Curves"*, *Graphics Gems*, [GitHub reference implementation](https://github.com/erich666/GraphicsGems/blob/master/gems/FitCurves.c)) or an **interpolating Catmull-Rom spline** through $K$ key points (where $K \in [4, 7]$ is chosen as the smallest integer whose Hausdorff residual to the mesh polyline is $\le 0.25 \times \text{gate\_limit}$).
- **Why Catmull-Rom beats B-spline control cages in OpenSCAD Customizer:** Every knot $\mathbf{P}_k = [x_k, y_k]$ of a Catmull-Rom spline lies **directly on the part boundary**! Moving `curve_1_knot_2_x` in the Customizer moves the physical curve through that exact coordinate, and OpenSCAD evaluates it in 4 lines of list-comprehension math without external libraries.

#### 3. Host-Anchored & Proportionally Scaled Hybrid Polyhedron Patch (`fits now`)
- **How it works:** [`2026-10-20-edge-rounds-design.md`](file:///home/heratiki/Source/stl2scad/docs/superpowers/specs/2026-10-20-edge-rounds-design.md) initially specifies that a polyhedron remainder stays fixed in the body frame. With almost zero extra effort, we can make the remainder **track parameter edits**:
  - Every remainder patch $R$ has a set of adjacent parametric faces $\{F_i\}$ in the RAG.
  - Anchor $R$'s local origin to the intersection of its host planes (e.g., `[body_width, body_height, body_depth]`), and if $R$ is a corner blend bounded by rounds $r_1, r_2, r_3$, apply `translate(anchor) scale([r1/r1_raw, r2/r2_raw, r3/r3_raw]) polyhedron(...)`!
  - At default slider values, `r_i / r_i_raw == 1.0`, so the Hausdorff distance is **unchanged to machine precision**, while changing a slider moves and scales the corner patch smoothly with the adjacent rounds.

#### 4. Cross-Sectional Loft / Skin Between Recovered 2D Sections (`fits with effort`)
- **How it works:** Slice an unresolved 3D region by $M$ parallel planes along its principal axis, resample each cross-section loop to $N$ corresponding vertices, parameterize each section's bounding box `(cx_i, cy_i, w_i, h_i)`, and emit an OpenSCAD `polyhedron()` whose `points` array is a list comprehension over the scaled sections and whose `faces` quad-strip indices are generated by a 3-line SCAD helper `_loft_faces(M, N)`.

---

## Specific Question 1: Arcs from Irregular Facets

### 1. Why Published Methods Succeed Where [`coarse.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py) and [`sections.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/sections.py) Fail

In our codebase, cylinder/arc recovery fails on irregular facets at three exact lines of code:
1. **[`coarse.py:97`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L97) (`if len(unique) != 2: graph.remove_node(p)`):** Assumes every planar strip of a cylinder is a rectangle whose vertices project along the cylinder axis $\hat{\mathbf{a}}$ to **exactly 2 points**. When a 45° chamfer or another surface clips a cylinder strip obliquely (as happens on `memo_cartridge` `F17/F18`, `memo_cartridge` `P61..P76`, and `memo_power_button` `P14..P49`), the clipped strip is a trapezoid or triangle with **3 or 4 distinct projected vertices** along the chord, so `coarse.py` deletes the node!
2. **[`coarse.py:48`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L48) (`tessellation()`) & [`sections.py:117`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/sections.py#L117) (`if model.segments is None: raise ValueError`):** Assumes every arc has uniform angular steps $\Delta\theta_i = k \frac{2\pi}{n}$. When CAD software exports an STL with a chord-height tolerance (e.g., OpenCASCADE [`BRepMesh_IncrementalMesh`](https://dev.opencascade.org/doc/overview/html/occt_user_guides__mesh.html)) or when a chamfer clips an arc mid-facet, the end chords have fractional angular steps $\Delta\theta_{\text{end}} < \Delta\theta_{\text{step}}$, causing `tessellation()` to return `segments=None` and `sections.py` to crash.
3. **[`pipeline.py:98`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L98) (`_extract_cylinders`):** Uses trianglecentroids (`points.mean(axis=1)`) to compute the radial direction in [`_cylinder_support`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L80). For an obliquely clipped or high-aspect-ratio triangle on a cylinder, the 3D centroid does **not** align radially with the face normal (because the centroid is shifted toward the wider end of the clipped strip, whereas the normal is the perpendicular bisector of the chord!).

### 2. Published Methods for Recovering Cylinders & Arcs from Irregular Tessellations

1. **Gaussian Sphere (Normal Covariance) Axis Recovery + Line-Projected Strip Grouping:**
   - **Source:** Lukács, Martin & Marshall (1998), *"Faithful least-squares fitting of spheres, cylinders, cones and tori for reliable segmentation"*, *ECCV 1998*, [DOI:10.1007/BFb0055696](https://doi.org/10.1007/BFb0055696); Várady, Facello & Terék (2007), *"Automatic extraction of surface structures in digital shape reconstruction"*, *Computer-Aided Design* 39(5):379–388, [DOI:10.1016/j.cad.2007.02.011](https://doi.org/10.1016/j.cad.2007.02.011).
   - **Method:** Any cylinder with axis $\hat{\mathbf{a}}$ maps its facet normals $\mathbf{n}_i$ to a great circle on the Gaussian sphere ($\mathbf{n}_i \cdot \hat{\mathbf{a}} = 0$). Regardless of how irregularly a planar facet $p$ is triangulated or clipped at its ends, **its vertices projected onto the 2D plane $\perp \hat{\mathbf{a}}$ lie on a single 2D line segment (chord)** with normal $\mathbf{n}_p$:
     $$\max_{\mathbf{v} \in p} \left| (\mathbf{v} - \bar{\mathbf{v}}_p) \cdot \mathbf{n}_p \right| \le \varepsilon_{\text{plane}} \quad \text{and} \quad |\mathbf{n}_p \cdot \hat{\mathbf{a}}| \le \sin(\theta_{\text{tol}})$$
     And the **2D endpoints of the maximal chord** of facet $p$ (the min and max projections along $\hat{\mathbf{a}} \times \mathbf{n}_p$) lie on the true cylinder circle whenever that side of the strip is shared with an adjacent strip in the smooth crease graph!
2. **Pratt (1987) / Taubin (1991) Algebraic Circle Fit + Levenberg–Marquardt / Gauss–Newton Geometric Fit on Boundary/Crease Vertices Only:**
   - **Source:** Pratt (1987), *"Direct least-squares fitting of algebraic surfaces"*, *SIGGRAPH 1987*, [DOI:10.1145/37401.37420](https://doi.org/10.1145/37401.37420); Taubin (1991), *"Estimation of planar curves, surfaces, and nonplanar space curves defined by implicit equations"*, *IEEE TPAMI* 13(11):1115–1138, [DOI:10.1109/34.103273](https://doi.org/10.1109/34.103273); Chernov & Lesort (2005), *"Least squares fitting of circles"*, *J. Math. Imaging Vis.* 23:239–252, [DOI:10.1007/s10851-005-0482-8](https://doi.org/10.1007/s10851-005-0482-8) ([arXiv:math/0301001](https://arxiv.org/abs/math/0301001)).
   - **Why Kåsa's linear least-squares fit in [`fitting.py:48`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/fitting.py#L48) is biased on small-sweep arcs:**
     - [`fitting.py:48-49`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/fitting.py#L48-L49) solves the unweighted Kåsa algebraic system $2x c_x + 2y c_y + (R^2 - c_x^2 - c_y^2) = x^2 + y^2$ over all raw triangle vertices `points.reshape(-1, 3)`.
     - Chernov & Lesort (2005) prove two critical flaws with this: (a) Kåsa's method has strong small-arc downward radius bias $O(\Delta\theta^{-2})$ when $\Delta\theta < 30^\circ$ (such as `F17/F18` in `memo_cartridge` where $\Delta\theta = 15.5^\circ$), and (b) passing `points.reshape(-1, 3)` without deduplicating vertices weights each vertex by its **triangle valence** (a vertex where 6 triangles meet gets $6\times$ the weight of a vertex with 2 triangles!). Furthermore, vertices lying strictly *inside* a clipped chord (where a chamfer cuts across the middle of a cylinder facet) lie **inside** the circumcircle by up to the sagitta $s = R(1 - \cos(\Delta\theta/2))$!
     - **The exact fix:** Fit the circle **only** to the deduplicated vertices that lie on **smooth longitudinal creases between cylinder strips** (which are guaranteed to be true cylinder surface generators, never interior chord-clipping points!), using **Taubin's fit** or **chord-normal intersection** ($\mathbf{n}_i \cdot (\mathbf{c} - \mathbf{m}_i) \times \hat{\mathbf{a}} = 0$, where $\mathbf{m}_i$ is the midpoint of an unclipped chord and $\mathbf{t}_i$ is the chord vector, since the perpendicular bisector of any chord of a circle passes through its exact center $\mathbf{c}$!).

### 3. Robust Statistical & Geometric Test: True Circular Arc vs. Spline / Ellipse / Free-Form Curve

Given an ordered chain of $m$ 2D projected crease vertices $\mathbf{p}_1, \dots, \mathbf{p}_m$ along a smooth curved region:

1. **Test 1 — Chord-Sagitta / Float32 Quantization Gate:**
   - Fit a circle $(\hat{\mathbf{c}}, \hat{R})$ via Taubin + 3 Gauss-Newton steps on $e_i = \|\mathbf{p}_i - \hat{\mathbf{c}}\| - \hat{R}$.
   - If $\max_i |e_i| \le \varepsilon_{\text{circle}} = \max(5\times 10^{-4}\text{ mm}, 2\times 10^{-5} D_{\text{diag}})$, it is **certifiably a true circular arc** (since CAD STL exports put generator vertices on the exact circle up to float32 precision).
2. **Test 2 — Wald–Wolfowitz Runs Test + Discrete Menger Curvature Trend (When $\varepsilon_{\text{circle}} < \max |e_i| \le \text{gate\_limit}$):**
   - **Source:** Wald & Wolfowitz (1940), [DOI:10.1214/aoms/1177731909](https://doi.org/10.1214/aoms/1177731909); Rosin & West (1995), *"Nonparametric segmentation of curves into various representations"*, *IEEE TPAMI* 17(12):1140–1153, [DOI:10.1109/34.476507](https://doi.org/10.1109/34.476507).
   - Compute the discrete Menger curvature $\kappa_i = \frac{2|(\mathbf{p}_i - \mathbf{p}_{i-1}) \times (\mathbf{p}_{i+1} - \mathbf{p}_{i-1})|}{\|\mathbf{p}_i - \mathbf{p}_{i-1}\|\|\mathbf{p}_{i+1} - \mathbf{p}_i\|\|\mathbf{p}_{i+1} - \mathbf{p}_{i-1}\|}$ at interior vertices $i=2,\dots,m-1$, and the Spearman rank correlation $\rho_s(i, \kappa_i)$ along the curve:
     - **True circle (noisy/quantized):** $|\rho_s(i, \kappa_i)| < 0.5$ and the sign sequence $\operatorname{sign}(e_i)$ has many runs.
     - **Spiral / Euler clothoid / Spline / Ellipse:** $|\rho_s(i, \kappa_i)| > 0.85$ (curvature changes monotonically) and $\operatorname{sign}(e_i)$ has $\le 4$ runs (`+ - +` or `- + - +`).
3. **Test 3 — Geometric BIC Model Selection (Circle [3 DOF] vs. Ellipse [4/5 DOF] vs. G1 Biarc [5 DOF] vs. Cubic Spline):**
   - **Source:** Torr (1998), *"Geometric Motion Segmentation and Model Selection"*, *Phil. Trans. R. Soc. A* 356:1321–1340, [DOI:10.1098/rsta.1998.0224](https://doi.org/10.1098/rsta.1998.0224); Fitzgibbon et al. (1999) ([DOI:10.1109/34.765658](https://doi.org/10.1109/34.765658)).
   - Fit an axis-aligned ellipse (4 DOF) and a general ellipse (5 DOF). If $\max_i |e_i^{\text{ellipse}}| \le \varepsilon_{\text{circle}}$ while $\max_i |e_i^{\text{circle}}| > 10 \varepsilon_{\text{circle}}$, classify as an **exact elliptical arc** (as on `memo_cartridge` feet where $\max |e_i^{\text{circle}}| = 0.31\text{ mm}$ vs. $\max |e_i^{\text{ellipse}}| = 0.000008\text{ mm}$!).

### Recommendations for Question 1 in `stl2scad`
- **`fits now` — Fix [`coarse.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py) for obliquely-clipped and irregular-chord cylinder strips:**
  1. In [`coarse.py:97`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L97), replace `if len(unique) != 2:` with a 2D line-segment check: project patch vertices perpendicular to `axis`, check that their 2D spread perpendicular to `normals[p]` is $\le \text{tolerance}$, and take the **2 extreme points along the chord** (or even better, only vertices shared on crease edges `graph.edges`) as `projected[p]`.
  2. In [`fitting.py:28`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/fitting.py#L28) (`fit_cylinder`), deduplicate projected 2D vertices (`_unique(xy, 1e-7)`) and exclude boundary vertices that are not on internal longitudinal creases before running least-squares circle fitting.
  3. In [`coarse.py:28`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L28) (`tessellation`), compute `step` from the median of interior (unclipped) angular gaps and do not fail when the two end gaps are smaller than `step` (clipped end facets!).
- **`fits now` — Add Ellipse vs. Circle vs. Spline test for `memo_cartridge` feet:**
  - Before Goal 8 work in [`2026-10-20-edge-rounds-design.md`](file:///home/heratiki/Source/stl2scad/docs/superpowers/specs/2026-10-20-edge-rounds-design.md), report to the user our empirical finding: `memo_cartridge` feet outlines (`C120–C125`) are **exact $3.0\text{ mm} \times 8.0\text{ mm}$ quarter-ellipses** ($\varepsilon_{\max} = 8\text{ nm}$), while the bottom/corner facets `P61..P110` are **exact $R=3.0\text{ mm}$ circular rounds** ($\varepsilon_{\max} = 5\text{ nm}$). Adding `SketchEllipseArc2D` (or scaling a circle by `[rx/ry, 1]`) gives exact sliders with zero error.

---

## Specific Question 2: Convex Edge Rounds, Chamfers, and Partial Arcs

### 1. Detection on B-Rep-Like Face Graphs Recovered from Meshes

In classical B-rep feature recognition, edge treatments are detected as **face-chain subgraphs** in the attributed Region Adjacency Graph (AAG/RAG):
- **Primary Sources:**
  - Joshi & Chang (1988), *"Graph-based heuristics for recognition of machined features from a 3D solid model"*, *Computer-Aided Design* 20(2):58–66, [DOI:10.1016/0010-4485(88)90050-4](https://doi.org/10.1016/0010-4485(88)90050-4).
  - Kós, Martin & Várady (2000), *"Methods to recover constant radius rolling ball blends in reverse engineering"*, *Computer Aided Geometric Design* 17(1–2):127–160, [DOI:10.1016/S0167-8396(99)00061-8](https://doi.org/10.1016/S0167-8396(99)00061-8).
  - Venkataraman, Sohoni & Rajadhyaksha (2002), *"Removal of blends from boundary representation models"*, *ACM SM 2002*, [DOI:10.1145/566282.566301](https://doi.org/10.1145/566282.566301).
  - Foucault et al. (2013), *"Adaptation of CAD model topology for finite element analysis"*, *Computer-Aided Design* 45(11):1406–1426, [DOI:10.1016/j.cad.2013.06.009](https://doi.org/10.1016/j.cad.2013.06.009).

#### Graph Signatures & Geometric Invariants for the 4 Target Cases

Let $F_1, F_2$ be two non-parallel planes with outward unit normals $\mathbf{n}_1, \mathbf{n}_2$ and offsets $d_1, d_2$. Their **virtual sharp intersection line** $L_{12}$ has direction $\hat{\mathbf{e}} = \frac{\mathbf{n}_1 \times \mathbf{n}_2}{\|\mathbf{n}_1 \times \mathbf{n}_2\|}$ and dihedral exterior angle $\alpha = \arccos(\mathbf{n}_1 \cdot \mathbf{n}_2) \in (0, \pi)$. In the 2D cross-section perpendicular to $\hat{\mathbf{e}}$, the virtual sharp corner is the unique solution $\mathbf{q}_{12}$ to:
$$\begin{bmatrix} \mathbf{n}_{1,\perp}^T \\ \mathbf{n}_{2,\perp}^T \end{bmatrix} \mathbf{q}_{12} = \begin{bmatrix} d_1 \\ d_2 \end{bmatrix}$$

1. **Convex 3D Edge Round (`edge_round_<n>_radius`):**
   - **Graph signature:** A `convex` cylinder face $C$ with axis $\hat{\mathbf{a}} \parallel \hat{\mathbf{e}}$ ($|\hat{\mathbf{a}} \cdot \mathbf{n}_1| < 10^{-3}, |\hat{\mathbf{a}} \cdot \mathbf{n}_2| < 10^{-3}$) adjacent to planes $F_1, F_2$ across two `tangent` edges (or via short clipped polygon-lip planes as in [`features.py:257`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py#L257)).
   - **Rolling-ball tangency invariant:** The cylinder center $\mathbf{c}_\perp$ in the 2D plane perpendicular to $\hat{\mathbf{a}}$ lies inside both half-spaces at distance $R$ from both planes:
     $$d_1 - \mathbf{n}_{1,\perp} \cdot \mathbf{c}_\perp = R \pm \varepsilon, \qquad d_2 - \mathbf{n}_{2,\perp} \cdot \mathbf{c}_\perp = R \pm \varepsilon$$
     and the theoretical sweep is $\Delta\theta = \alpha = \arccos(\mathbf{n}_1 \cdot \mathbf{n}_2)$ (so $\Delta\theta = 90^\circ$ for orthogonal hosts).
2. **Symmetric Planar Chamfer (`chamfer_<n>_width`):**
   - **Graph signature:** A narrow planar strip $F_c$ (with aspect ratio $L / w > 2$ or width $w \ll \min(\text{width}(F_1), \text{width}(F_2))$) sharing two parallel `convex` mesh boundary edges of equal length with planes $F_1$ and $F_2$, such that $\mathbf{n}_c \cdot \hat{\mathbf{e}} = 0$.
   - **Symmetry & parameterization invariant:** A chamfer between $F_1$ and $F_2$ is **symmetric** iff its normal bisects $\mathbf{n}_1$ and $\mathbf{n}_2$:
     $$\left\| \mathbf{n}_c - \frac{\mathbf{n}_1 + \mathbf{n}_2}{\|\mathbf{n}_1 + \mathbf{n}_2\|} \right\| \le \sin(1^\circ)$$
     For orthogonal hosts ($\mathbf{n}_1 \cdot \mathbf{n}_2 = 0$), this is a 45° chamfer ($\mathbf{n}_c = \frac{\mathbf{n}_1 + \mathbf{n}_2}{\sqrt{2}}$). Let $\mathbf{q}_{12}$ be the virtual sharp corner of $F_1$ and $F_2$. The **setback width** (leg width along each host face, which is standard CAD `chamfer_width` in SolidWorks/Fusion/FreeCAD and matches `hand_check` "0.8 x 0.8" in [`memo_cartridge_expected.json`](file:///home/heratiki/Source/stl2scad/tests/data/segmentation/real/memo_cartridge_expected.json#L8)) is:
     $$w_{\text{leg}} = \frac{(\mathbf{q}_{12} - \mathbf{p}_c) \cdot \mathbf{n}_c}{\cos(\alpha / 2)} = \sqrt{2}\, (\mathbf{q}_{12} - \mathbf{p}_c) \cdot \mathbf{n}_c \quad (\text{for } \alpha = 90^\circ)$$
     while the bevel face width is $w_{\text{bevel}} = 2 w_{\text{leg}} \sin(\alpha / 2)$ ($= \sqrt{2} w_{\text{leg}}$ for $90^\circ$). If $|\mathbf{n}_c \cdot \mathbf{n}_1 - \mathbf{n}_c \cdot \mathbf{n}_2| > \sin(1^\circ)$, flag and report it as an **asymmetric chamfer** per [`2026-10-20-edge-rounds-design.md`](file:///home/heratiki/Source/stl2scad/docs/superpowers/specs/2026-10-20-edge-rounds-design.md#L120).
3. **Partial Profile Arcs Clipped by Chamfers (`memo_cartridge` `F17/F18` = `C116/C117`):**
   - **What is happening in `memo_cartridge` `F17/F18`:** `F17` and `F18` are $R = 3.0\text{ mm}$ convex cylinders along Y (the plate extrusion axis), tangent to the bottom plane `F16` ($\mathbf{n} = [0, 0, -1]$), with sweep $15.5^\circ$. Why does the arc stop at $15.5^\circ$ instead of $90^\circ$? Because the vertical side walls at $X = 2.625$ and $X = 83.225$ end at $Z = 6.563 + 3.0(1 - \cos 15.5^\circ) \approx 6.67\text{ mm}$, and the front $+Y$ face has a 45° perimeter chamfer (`F11`/`F13`)!
   - **General rule:** Any cylinder $C$ whose axis $\hat{\mathbf{a}}$ is parallel to the extrusion axis ($\hat{\mathbf{a}} \parallel \hat{\mathbf{z}}_{\text{part}}$), regardless of whether it is tangent to 2 planes (full $90^\circ$ corner round), 1 plane + 1 convex edge (partial profile arc like `F17/F18`), or 2 parallel opposite planes ($180^\circ$ rib end like `memo_power_button` `F12/F13`), is a **2D Sketch Arc (`SketchArc2D`)** of the extrusion profile, NOT a 3D spatial feature!
   - Why did `F17/F18` reach [`features.py:353`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/features.py#L353) (`Unsupported cylinder topology at F17`)? Because [`detect_section_features`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/sections.py#L162) returned `None` (since `memo_cartridge` has 45° chamfers and feet that don't span the plate thickness), falling back to `_cylinder_features` in `features.py`, which only knows about $90^\circ$ concave fillets, bosses, blind holes, and through holes!
   - **How Defeaturing (A1) solves this automatically:** Once the 3D 45° chamfers (`P1, P11, P12, P13`) and the feet are separated from the plate slab, `F17` and `F18` are simply `SketchArc2D` segments on the 2D plate outline, which [`section_ir.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/section_ir.py) and [`section_emit.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/section_emit.py) **already know how to parameterize and emit** via `_arc(c, r, start_deg, sweep_deg, phase_deg, segments)`!
4. **180° Half-Round Rib Ends (`memo_power_button` `F12/F13` = `C54/C55`):**
   - **Graph signature:** Convex cylinder $C$ with $\Delta\theta \approx 180^\circ$, tangent to two parallel planes $F_a, F_b$ with **opposite** normals ($\mathbf{n}_a \cdot \mathbf{n}_b \approx -1$) separated by distance $w = 2R$.
   - **Parameterization constraint:** In a full-round rib end, the rib thickness $w$ and the end radius $R$ are **geometrically coupled**: if `corner_<n>_radius` is exposed as a slider, either:
     - Keep the end center fixed and let the arc bulge/shrink while constraining `corner_<n>_radius >= rib_thickness / 2`, OR
     - Link the two parallel side walls of the rib to `rib_center +/- corner_<n>_radius` so changing `corner_<n>_radius` changes the rib thickness while preserving tangency! (Or keep rib walls fixed and move the tangent join angles $\pm\arcsin(\text{half\_width}/r)$).

### 2. How to Re-Emit 3D Edge Rounds and Chamfers in OpenSCAD

There are three ways to emit 3D rounds and chamfers in OpenSCAD:
1. **`minkowski()` / `offset()` on the whole body:**
   - **Verdict: `does not fit`**. In OpenSCAD, `minkowski()` rounds *every* convex edge simultaneously with the same radius, cannot give independent sliders to individual edges, alters outer dimensions unless compensated, and is $O(N^2)$ slow in CGAL.
2. **2D Profile Incorporation (for all rounds/chamfers whose axis $\parallel$ the slab extrusion axis):**
   - **Verdict: `fits now`**. Any corner round (`memo_power_button` `F1816–F1818`), rib end (`F12/F13`), or partial profile arc (`memo_cartridge` `F17/F18`) whose axis equals the extrusion axis belongs inside the 2D `polygon(_outline)` of that extrusion slab using `_arc(...)` in [`section_emit.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/section_emit.py).
3. **CSG Subtraction of a Parametric Edge-Cutter Wedge (`BooleanDifference`) for 3D Edge Rounds & Chamfers:**
   - **Verdict: `fits now`**. Just as [`emit.py:224-230`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/emit.py#L224-L230) emits a *concave* fillet as an additive `linear_extrude` of a 2D wedge minus a circle (`difference() { polygon(wedge); circle(r=fillet_r); }`), a **convex 3D edge round** is the **exact dual**:
     - Extend the base body's two host planes $F_1, F_2$ to their sharp corner $\mathbf{q}_{12}$.
     - In `BooleanDifference.cuts`, subtract a **negative corner-cutter wedge** extruded along the edge direction $\hat{\mathbf{e}}$ (extended by `_join_epsilon` at both ends):
       ```openscad
       // Convex 3D edge round cutter along edge frame:
       multmatrix(edge_frame) translate([0, 0, -_join_epsilon])
         linear_extrude(height = edge_length + 2*_join_epsilon)
           difference() {
             // Wedge extending outside the sharp corner by _join_epsilon:
             polygon(points = [
               [q.x + s_x*_join_epsilon, q.y + s_y*_join_epsilon],
               [c.x, q.y + s_y*_join_epsilon],
               [c.x, c.y],
               [q.x + s_x*_join_epsilon, c.y]
             ]);
             translate([c.x, c.y]) rotate(phase_deg)
               circle(r = edge_round_1_radius, $fn = edge_round_1_segments);
           }
       ```
     - Similarly, a **3D symmetric chamfer** subtracts a right-isosceles triangle cutter of leg width `chamfer_1_width + _join_epsilon` along the sharp edge!
     - **Why this is ideal for `stl2scad`:** (a) It preserves the exact original polygon phase `$fn = edge_round_1_segments` and `phase_deg`, so at the measured radius it reproduces the STL facets to **$< 10^{-5}\text{ mm}$ Hausdorff distance**; (b) when the user drags `edge_round_1_radius` or `chamfer_1_width` in Customizer, the cutter cleanly removes more or less of the sharp corner!

---

## Specific Question 3: Hybrid Output (Parametric Solid + Free-Form Remainder)

### 1. How Reverse-Engineering Kernels Combine Parametric B-Reps with Mesh Patches

Commercial reverse-engineering systems fall into two architectural camps:
1. **Surface-Fit & Trim-to-Solid (Geomagic Design X *Hybrid Modeling*, SOLIDWORKS *ScanTo3D*, Point2CAD [arXiv:2312.04962](https://arxiv.org/abs/2312.04962)):**
   - Fits analytic surfaces to known regions and NURBS patches to free-form regions, then extends neighboring surfaces and intersects/trims them into a single watertight B-rep (`TopoDS_Solid`).
2. **Mixed Facet-Analytic B-Rep (Siemens Parasolid *Convergent Modeling* [Siemens Whitepaper](https://plm.sw.siemens.com/en-US/nx/cad-online/convergent-modeling/), CGAL *Polygon Mesh Processing / Corefinement* [CGAL Docs](https://doc.cgal.org/latest/Polygon_mesh_processing/index.html)):**
   - Keeps the unresolved region as a triangulated facet B-rep face, closes it into a valid solid volume bounded by the adjacent analytic faces, and performs exact Boolean `union()` or `difference()` with the parametric body.

Because OpenSCAD's CGAL/Manifold backend requires **every operand of `union()` or `difference()` to be a closed, 2-manifold, watertight solid** (an open surface patch in `polyhedron()` causes CGAL assertion failures or silent non-manifold rejection), we must close any open free-form triangle patch $M_{\text{free}}$ into a valid solid volume $S_{\text{free}}$ before joining it to the parametric body $S_{\text{param}}$.

### 2. How to Cut and Close an Open Free-Form Patch into a Watertight Solid for CSG

Suppose a connected component of unfitted triangles $M_{\text{free}}$ (with outward normals) has one or more open boundary loops $\partial M_{\text{free}} = \{L_1, \dots, L_m\}$, where each boundary edge $e \in \partial M_{\text{free}}$ is shared with a fitted analytic face $F_k$ of the parametric body $S_{\text{param}}$.

First, determine the **polarity** of $M_{\text{free}}$ relative to the defeatured (sharp-extended) parametric body $S_{\text{param}}$:
- Evaluate the signed distance $d(\mathbf{x}, S_{\text{param}})$ of the interior vertices of $M_{\text{free}}$ relative to the extended host planes of $S_{\text{param}}$:
  - **Case A — Subtractive Remainder (e.g., a 3D corner round/blend like `F118/F119` in `memo_cartridge` or `F56` in `memo_power_button`):** All interior vertices of $M_{\text{free}}$ lie **inside** the sharp-extended parametric body $S_{\text{param}}$, and the outward normals of $M_{\text{free}}$ point toward the exterior sharp corner $\mathbf{q}$.
    - **How to close $M_{\text{free}}$ into a subtractive cutter solid $S_{\text{cut}}$:**
      1. Reverse the triangle winding of $M_{\text{free}}$ so its normals point *into* the corner wedge being removed.
      2. For each adjacent host plane $F_k$ (expanded outward by $\epsilon = \text{\_join\_epsilon}$), project the boundary chain $\partial M_{\text{free}} \cap F_k$ onto the offset plane $F_k^{+\epsilon}$ and triangulate the planar polygon on $F_k^{+\epsilon}$ (plus the sharp corner apex $\mathbf{q}^{+\epsilon}$).
      3. Alternatively (and even simpler, **zero-triangulation method**): let $\mathbf{a}_{\text{out}}$ be a single point strictly outside the sharp corner by $\epsilon$ (e.g. $\mathbf{a}_{\text{out}} = \mathbf{q} + \epsilon \sum_k \mathbf{n}_k$). Connect every directed boundary edge $(u, v) \in \partial M_{\text{free}}$ to the apex $\mathbf{a}_{\text{out}}$ to form a **closed pyramidal fan (conical closure)**!
      4. **Theorem (Conical / Apex Closure):** If $M_{\text{free}}$ is star-shaped with respect to an exterior apex $\mathbf{a}_{\text{out}}$ (which holds for **every** convex corner blend, chamfer intersection, or setback vertex because all patch normals have positive dot product with $\mathbf{a}_{\text{out}} - \mathbf{x}$!), then uniting $M_{\text{free}}$ (with flipped normals) and the triangle fan $\{(u, v, \mathbf{a}_{\text{out}}) : (u, v) \in \partial M_{\text{free}}\}$ produces a **guaranteed watertight, non-self-intersecting 2-manifold `polyhedron`** with zero 2D polygon triangulation needed! Subtracting this closed pyramid from the extended parametric body in `difference()` leaves the exact surface $M_{\text{free}}$ on the solid!
  - **Case B — Additive Remainder (an organic boss/protrusion extending outside $S_{\text{param}}$):** All interior vertices of $M_{\text{free}}$ lie **outside** the host face(s) of $S_{\text{param}}$.
    - **How to close $M_{\text{free}}$ into an additive solid $S_{\text{add}}$:**
      1. Choose an interior anchor point $\mathbf{a}_{\text{in}}$ strictly **inside** the parametric body by $\epsilon$ (e.g., the centroid of $\partial M_{\text{free}}$ shifted along $-\mathbf{n}_{\text{host}}$ by $2\epsilon$, or orthogonally project all vertices of $\partial M_{\text{free}}$ along $-\mathbf{n}_{\text{host}}$ by $2\epsilon$ into $S_{\text{param}}$ and close with a bottom fan).
      2. Connect each directed boundary edge $(v, u) \in \partial M_{\text{free}}$ to $\mathbf{a}_{\text{in}}$ (or the projected base loop). Because $\mathbf{a}_{\text{in}}$ lies inside $S_{\text{param}}$, the closing fan is completely buried inside $S_{\text{param}}$ during `union()`, leaving only $M_{\text{free}}$ exposed on the boundary!
  - **Case C — Mixed / Saddle Remainder (crosses the extended host surface):**
    - Both add an outward-buried fan to `union()` and subtract an inward-buried fan in `difference()`, or clip $S_{\text{param}}$ with a bounding box of $M_{\text{free}}$ and `union()` the extruded patch prism.

### 3. Keeping the Remainder Placed When Parameters Change
- **Minimum requirement (per [`2026-10-20-edge-rounds-design.md`](file:///home/heratiki/Source/stl2scad/docs/superpowers/specs/2026-10-20-edge-rounds-design.md#L75)):** Put the `polyhedron()` inside the top-level `multmatrix(part_frame)` so it moves with the part frame.
- **Recommended improvement (`fits now`, ~20 lines of code):** Wrap the `polyhedron()` in `translate([host_x - raw_host_x, host_y - raw_host_y, host_z - raw_host_z])` where `host_x, host_y, host_z` are the bound parameter expressions of the host planes meeting at that corner (e.g. `body_width`, `body_height`). At default slider values, the translation is `[0, 0, 0]`; when the user changes `body_width`, the corner remainder rides along with the corner instead of floating in mid-air!

---

## Specific Question 4: Screw Holes, Threads, Countersinks, and Counterbores

### 1. Counterbores and Countersinks (Classical RAG Recognition)
- **Primary Sources:** Marefat & Kashyap (1990), *"Geometric reasoning for recognition of three-dimensional object features"*, *IEEE TPAMI* 12(10):949–965, [DOI:10.1109/34.58868](https://doi.org/10.1109/34.58868); Vandenbrande & Requicha (1993), *"Spatial reasoning for the automatic recognition of machinable features in solid models"*, *IEEE TPAMI* 15(12):1269–1285, [DOI:10.1109/34.250845](https://doi.org/10.1109/34.250845).
- **Detection in our RAG (`fits now`):**
  - **Counterbore (`HoleCounterbore` in [`ir.py:681`](file:///home/heratiki/Source/stl2scad/stl2scad/core/ir.py#L681)):** A coaxial chain of two `concave` cylinders $C_{\text{bore}}$ ($R_1$) and $C_{\text{shank}}$ ($R_2 < R_1$) with $\hat{\mathbf{a}}_1 \parallel \hat{\mathbf{a}}_2$ and coaxial distance $< \varepsilon$, connected by an annular planar step face $P_{\text{step}}$ ($\mathbf{n}_{\text{step}} \parallel \hat{\mathbf{a}}_1$) where edge $(C_{\text{bore}}, P_{\text{step}})$ is `concave` and edge $(P_{\text{step}}, C_{\text{shank}})$ is `convex`.
  - **Countersink (`HoleCountersink`):** Same coaxial chain, except the upper face is a `concave` **cone** $K_{\text{sink}}$ (with axis $\hat{\mathbf{a}}_K \parallel \hat{\mathbf{a}}_2$ and half-angle $\gamma \in [40^\circ, 60^\circ]$; standard metric ISO 10642 is $2\gamma = 90^\circ$, Unified/ANSI is $82^\circ$ or $100^\circ$) meeting $C_{\text{shank}}$ along a `convex` circular crease!
  - **How to add cone fitting to [`fitting.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/fitting.py) (`fits now`):** On the Gaussian sphere, the normals $\mathbf{n}_i$ of a cone with axis $\hat{\mathbf{a}}$ and half-angle $\gamma$ lie on a **small circle** $\mathbf{n}_i \cdot \hat{\mathbf{a}} = \pm\sin\gamma$ (Lukács et al. 1998, [DOI:10.1007/BFb0055696](https://doi.org/10.1007/BFb0055696)). Thus solving the linear system $\mathbf{N}\mathbf{v} = \mathbf{1}$ directly recovers the cone axis $\hat{\mathbf{a}} = \mathbf{v}/\|\mathbf{v}\|$ and half-angle $\sin\gamma = 1/\|\mathbf{v}\|$ in 5 lines of numpy!

### 2. Modeled Threads vs. Plain Tap / Clearance / Heat-Set Insert Holes

In 3D-printed mechanical parts, holes for fasteners appear in four distinct ways:
1. **Modeled helical thread** (explicit helical V-ridge triangles inside the bore or on a shaft).
2. **Plain cylindrical hole sized for a tap / self-tapping screw** (e.g., $\varnothing 2.5\text{ mm}$ for M3$\times$0.5 tap per [ISO 2306 / ISO 68-1](https://www.iso.org/standard/3707.html)).
3. **Plain cylindrical hole (or stepped/tapered bore) sized for a brass heat-set insert** (e.g., CNC Kitchen / Ruthex M3 insert uses $\varnothing 4.0\text{ mm}$ to $4.4\text{ mm}$ blind or stepped bore; Voron standard M3 heat-set is $\varnothing 4.0\text{ mm} \times 5.0\text{ mm}$).
4. **Plain clearance hole** (e.g., $\varnothing 3.2\text{–}3.4\text{ mm}$ for M3 per ISO 273).

#### How to Distinguish Them Geometrically
- **Modeled Thread vs. Plain Cylinder:**
  - A plain hole is a single `concave` cylinder face where all vertices lie at constant radius $r_i = R \pm \varepsilon$ and normals satisfy $\mathbf{n}_i \cdot \hat{\mathbf{a}} = 0$.
  - A **modeled thread** (ISO 68-1 metric $60^\circ$ or Whitworth $55^\circ$) is a high-triangle-count tubular region ($> 200$ triangles) around a central axis $\hat{\mathbf{a}}$ where:
    1. **Bimodal normal tilt:** Instead of $\mathbf{n}_i \cdot \hat{\mathbf{a}} \approx 0$, the axial normal components cluster tightly around **two symmetric flank angles** $\mathbf{n}_i \cdot \hat{\mathbf{a}} \approx \pm\cos(\theta_{\text{thread}}/2)$ ($\pm\cos 30^\circ = \pm 0.866$ for $60^\circ$ metric; $\pm\cos 27.5^\circ = \pm 0.887$ for $55^\circ$ Whitworth)!
    2. **Radial distribution ($D_{\text{major}}, D_{\text{minor}}$):** In cylindrical coordinates $(r_i, \phi_i, z_i)$ around $\hat{\mathbf{a}}$ (where $\hat{\mathbf{a}}$ is the centroidal axis of the tubular boundary loops), the radii span a band $[r_{\min}, r_{\max}]$ of depth $H_{\text{actual}} = r_{\max} - r_{\min} \approx \frac{5}{8} H = \frac{5\sqrt{3}}{16} P \approx 0.541 P$ (ISO 68-1).
    3. **Helical Pitch $P$ and Handedness via Helical Phase Regression / 1D FFT:**
       - Along a helix of pitch $P$ and handedness $s \in \{+1\text{ (RH)}, -1\text{ (LH)}\}$ (with $N_{\text{starts}}$ starts, usually 1), the radius $r_i$ is a periodic function of the **helical phase** $\psi_i = z_i - s \frac{P}{2\pi} \phi_i \pmod P$.
       - **Algorithm (~25 lines of numpy):** Bin vertices by angle $\phi \in [-\pi, \pi)$ into 16 angular sectors; in each sector, compute the dominant axial frequency $f_z = 1/P$ of $r(z)$ via 1D FFT or autocorrelation. Then fit the phase slope $\frac{d z_{\text{crest}}}{d\phi} = s \frac{P}{2\pi}$ across the 16 sectors by circular-linear regression: the slope magnitude gives **pitch $P$**, the sign $s = \operatorname{sign}(dz/d\phi)$ gives **right-handed ($+$) vs. left-handed ($-$)**, and the flank normal angle gives **$60^\circ$ vs. $55^\circ$**!
- **Telling a Tap Hole from a Heat-Set Insert Hole from a Clearance Hole:**
  - Geometrically, a non-threaded tap hole, heat-set insert hole, and clearance hole are **all plain cylinders** (or stepped cylinders). No algorithm can know with 100% certainty from geometry alone whether a $\varnothing 4.0\text{ mm}$ hole is an M4 tap hole (M4$\times$0.7 tap drill is $3.3\text{ mm}$, clearance is $4.3\text{ mm}$, heat-set insert for M3 is $4.0\text{ mm}$, dowel pin is $4.0\text{ mm}$) — **say plainly: this is semantically ambiguous without context**.
  - **Best practice (`fits now`):** Emit the exact measured cylinder `hole_1_diameter = 4.0`, and add a **non-binding diagnostic/comment hint** in the SCAD header above the parameter by matching `(diameter, depth)` against a table of standard 3D-printing fastener dimensions (e.g., `// hole 1 diameter (raw 4.0; matches M3 heat-set insert Ø4.0 or M4 tight hole)`).

### 3. How to Emit Modeled Threads in OpenSCAD Without Breaking the Hausdorff Gate

**Critical Trap:** If an input STL has a modeled thread (say, rendered from Fusion 360, SolidWorks, or `threads.scad`), and we emit `include <BOSL2/threading.scad> threaded_rod(d=..., pitch=..., l=...)`, it will **almost certainly fail the $0.05\text{ mm}$ Hausdorff gate**! Why?
1. External libraries (`BOSL2`, `threads.scad`) may not be installed in the user's or CI's OpenSCAD path.
2. Even with identical `(major_d, minor_d, pitch, flank_angle)`, a helical thread has **3 additional degrees of freedom** that move the surface by up to $H_{\text{actual}} \approx 0.54 P$ (which is $0.81\text{ mm}$ for M10$\times$1.5, **$16\times$ larger than the $0.05\text{ mm}$ gate!**):
   - **Helical start phase $\phi_0 \in [0, 2\pi)$** (rotational clocking of the thread start at $z = z_0$).
   - **Crest/root truncation flat widths** ($P/8$ vs. $P/4$ vs. rounded root, or printer `$slop` offset).
   - **Lead-in / lead-out bevel termination** (where the thread helix clips against the end cap vs. tapers out).

#### The Solution: Dual-Mode Emission (Exact Mesh Patch at Default + Self-Contained Parametric Helix on Edit)
- **Recommendation (`fits now` for hole/counterbore/countersink; `fits with effort` for modeled threads):**
  1. **Never depend on external `include <BOSL2/...>` by default** (since headless OpenSCAD in CI and standard installations do not ship BOSL2). Instead, emit a self-contained 12-line OpenSCAD `_iso_thread(...)` polyhedron-sweep helper (or optional commented-out `// threaded_rod(...)` snippet).
  2. **Fit the helical phase $\phi_0$ and exact axial slice profile $(r(z), z)$** of the thread tooth from the mesh. If the reconstructed self-contained `_iso_thread(d_major, d_minor, pitch, phi0, ...)` passes the $0.05\text{ mm}$ Hausdorff gate (which it does when the thread was generated by `linear_extrude(twist=...)` or a standard uniform sweep), emit it directly!
  3. **If lead-in bevels or CAD root fillets cause the analytic helix to miss the $0.05\text{ mm}$ gate:** Emit the recovered thread parameters (`thread_1_major_d`, `thread_1_pitch`, `thread_1_length`) linked to a boolean or change-detector expression:
     ```openscad
     _thread_1_edited = (thread_1_major_d != 10.0 || thread_1_pitch != 1.5 || thread_1_length != 12.0);
     if (_thread_1_edited) {
         _parametric_thread(thread_1_major_d, thread_1_pitch, thread_1_length, ...);
     } else {
         polyhedron(points=_thread_1_raw_pts, faces=_thread_1_raw_faces);
     }
     ```
     At default values (`_thread_1_edited == false`), the Hausdorff distance to the input mesh is **$0.0000\text{ mm}$** (passing the gate with certainty), while the moment the user changes `thread_1_major_d` or `thread_1_pitch` in the Customizer, it seamlessly switches to the parametric helical generator!

---

## Specific Question 5: Overall Method — Classical vs. Modern Learning Pipelines

We evaluated 13 major reverse-engineering and CAD-reconstruction pipelines against the constraints of [`stl2scad`](file:///home/heratiki/Source/stl2scad/CLAUDE.md): **pure Python, deterministic, CPU-only, numpy/scipy/networkx/trimesh, no GPU, no external training data, and strict $0.05\text{ mm}$ Hausdorff verification**.

### Comparison of Published Frameworks & What Transfers to `stl2scad`

| Method & Primary Source | Core Algorithmic Idea | Transfers to CPU-Only Deterministic Python? | Verdict & Specific Technique to Adopt |
|---|---|---|---|
| **Efficient RANSAC** — Schnabel, Wahl & Klein (2007), *CGF* 26(2):214–226 ([DOI:10.1111/j.1467-8659.2007.01016.x](https://doi.org/10.1111/j.1467-8659.2007.01016.x); [CGAL Docs](https://doc.cgal.org/latest/Shape_detection/index.html)) | Minimal 2-point-with-normals sampling ($\mathbf{a} = \mathbf{n}_1 \times \mathbf{n}_2$ for cylinders; intersection of normal lines for spheres; plane through $\mathbf{n}_1, \mathbf{n}_2$ for cones) + octree local sampling + connected-component inlier extraction. | **Yes (100%)**. Our [`_extract_cylinders`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/pipeline.py#L94) already uses a simplified version of this (sampling 3 patches). | **`fits now`**. Adopt Schnabel's **2-patch normal-cross minimal hypothesis** for cylinders and cones (`fitting.py`) instead of 3-patch SVD, which fails when 2 of 3 sampled patches have nearly parallel normals. |
| **Classical B-Rep Reverse Engineering** — Várady, Martin & Cox (1997) ([DOI:10.1016/S0010-4485(96)00054-1](https://doi.org/10.1016/S0010-4485(96)00054-1)); Benkő, Martin & Várady (2001) ([DOI:10.1016/S0010-4485(00)00139-1](https://doi.org/10.1016/S0010-4485(00)00139-1)); Benkő et al. (2002) ([DOI:10.1016/S0167-8396(02)00083-3](https://doi.org/10.1016/S0167-8396(02)00083-3)) | Hierarchy of primary surfaces (planes, cylinders, cones) and secondary blends (rolling-ball fillets/rounds); **defeature blends first**, intersect primary surfaces to recover sharp topology, and apply **constrained fitting (beautification)** to enforce orthogonality/tangency/coaxiality. | **Yes (100%)**. Pure linear algebra, graph rewriting, and constrained least squares. | **`fits now` (Highest Value)**. Directly fixes the #1 architectural bottleneck in `features.py`: strip chamfers/rounds/corner blends from the RAG *before* recovering the base extrusion! |
| **Point2CAD** — Liu, Obukhov, Wegner & Schindler (CVPR 2024, [arXiv:2312.04962](https://arxiv.org/abs/2312.04962); [GitHub](https://github.com/prs-eth/point2cad)) | Decouples segmentation from topology: fits analytic primitives (planes, spheres, cylinders, cones) via classical least squares (and INRs for freeform), then recovers **exact B-rep edges and corners by intersecting adjacent extended surfaces** and clipping them via point proximity. | **The topology/intersection engine transfers 100%** (it is explicitly non-neural!). The neural point-cloud segmentation backbone (ParseNet/HPNet) is unnecessary on clean STL meshes where our normal/crease segmentation is much sharper. | **`fits now`**. Adopt Point2CAD's **analytic surface extension + pairwise intersection curve + vertex clipping** to reconstruct sharp corners obscured by rounds/chamfers. |
| **ComplexGen** — Guo et al. (SIGGRAPH 2022, [arXiv:2205.14573](https://arxiv.org/abs/2205.14573); [GitHub](https://github.com/guohaoxiang/ComplexGen)) | Predicts 0-cells (corners), 1-cells (curves), and 2-cells (patches) jointly via a SparseCNN + Transformer, then solves a **global Integer Linear Program (ILP) with chain-complex boundary validity constraints** ($\partial\partial = 0$, every curve bounds 2 faces, every loop is closed). | The neural network (`does not fit`). The **chain-complex topological validity constraints** transfer directly as deterministic graph checks. | **Neural net: `does not fit`**. **Chain-complex boundary checks: `fits with effort`** to validate RAG edits during defeaturing. |
| **ParSeNet / HPNet / SED-Net** — Sharma et al. (ECCV 2020, [arXiv:2003.12181](https://arxiv.org/abs/2003.12181)); Yan et al. (ICCV 2021, [arXiv:2105.10620](https://arxiv.org/abs/2105.10620)); Li et al. (SIGGRAPH 2023, [DOI:10.1145/3588432.3591547](https://doi.org/10.1145/3588432.3591547), [GitHub](https://github.com/yuanqili78/SED-Net)) | Point-cloud neural networks that combine point features, normal features, and sharp-edge adjacency to cluster points into primitive/B-spline patches. | **Neural weights: `does not fit`**. However, HPNet & SED-Net's core insight — **weighting region adjacency by sharp-edge dihedral confidence and second-order normal variation** — is pure geometry. | **Neural nets: `does not fit`** (require PyTorch/GPU and have $\sim 1\text{–}2\%$ boundary label bleed that ruins $0.05\text{ mm}$ CAD edges). **Sharp-edge-gated region merging: `fits now`** (already used in `pipeline.py`). |
| **NVD-Net (Split-and-Fit)** — Liu et al. (SIGGRAPH 2024, [arXiv:2406.05261](https://arxiv.org/abs/2406.05261)) | Partitions 3D space into Voronoi cells aligned with B-rep faces, then fits one primitive per cell. | Neural Voronoi predictor (`does not fit`). | **`does not fit`**. Surface triangle ownership on a manifold STL already provides exact surface partitioning without 3D voxelization. |
| **BRepNet / UV-Net** — Lambourne et al. (CVPR 2021, [arXiv:2104.00706](https://arxiv.org/abs/2104.00706)); Jayaraman et al. (CVPR 2021, [arXiv:2006.10211](https://arxiv.org/abs/2006.10211)) | Topological message passing on directed coedges (`next`, `prev`, `mate`, `face`, `edge`) and UV-grid feature pooling on B-rep faces to classify machining features (holes, slots, pockets, fillets, chamfers). | Neural GNN (`does not fit`). However, **BRepNet's Half-Edge / Coedge walk kernel** (orienting every boundary loop as an ordered cycle of directed coedges around each face) is a fundamental data structure upgrade over our undirected `nx.Graph`! | **Neural GNN: `does not fit`**. **Directed Coedge Data Structure in [`models.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/models.py): `fits now`**. An undirected `nx.Graph` loses outer-loop vs. inner-hole-loop distinction and multi-edge adjacency (when two faces touch along two separate edges!). |
| **Point2Cyl** — Uy et al. (CVPR 2022, [arXiv:2112.09329](https://arxiv.org/abs/2112.09329); [GitHub](https://github.com/mikaelaangelina/point2cyl)) | Decomposes a shape into a set of **Extrusion Cylinders** (each defined by an extrusion axis $\hat{\mathbf{e}}$, axial interval $[h_{\min}, h_{\max}]$, a 2D closed sketch profile, and a boolean label: barrel vs. cap). | Neural point segmenter (`does not fit`). **The "Barrel + Cap" Extrusion Cylinder decomposition and 2D SDF/polygon sketch fitting transfer 100%** to our RAG! | **Extrusion-Barrel Clustering: `fits now`**. Group all plane and cylinder faces in our RAG whose normals are orthogonal to a common axis $\hat{\mathbf{e}}$ ($\mathbf{n}_i \cdot \hat{\mathbf{e}} = 0$) and that share an axial height interval $[z_a, z_b]$ into an **Extrusion Barrel**! |
| **DeepCAD / SECAD-Net / ExtrudeNet** — Wu et al. (ICCV 2021, [arXiv:2105.09492](https://arxiv.org/abs/2105.09492)); Li et al. (CVPR 2023, [arXiv:2303.10613](https://arxiv.org/abs/2303.10613)); Ren et al. (ECCV 2022, [arXiv:2209.15632](https://arxiv.org/abs/2209.15632)) | Represent any mechanical part as a sequence of **(2D Sketch $\to$ Linear Extrude $[z_{\min}, z_{\max}]$ $\to$ Boolean Union/Difference)**. | Neural auto-encoders and differentiable SDFs (`does not fit`). The **canonical Sketch-Extrude-Boolean IR paradigm** is already what [`stl2scad/core/ir.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/ir.py) uses! | **Neural training: `does not fit`**. **Multi-Extrude Boolean Sequence (generalizing single-body in `to_ir.py` to $K$ extrusions): `fits now`**. |

---

### Summary of Concrete Actionable Upgrades for `stl2scad/core/segmentation/`

To pass `memo_cartridge`, `memo_power_button`, and the broader real-world corpus while keeping 100% of the existing 311 passing tests green:

1. **Upgrade [`coarse.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py) & [`fitting.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/fitting.py) (`fits now`):**
   - Replace `len(unique) != 2` ([`coarse.py:97`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L97)) with 2D chord-collinearity perpendicular to $\hat{\mathbf{a}}$ so cylinder strips obliquely clipped by chamfers or ellipses (`P61..P76` in `memo_cartridge`, `P14..P49` in `memo_power_button`) are recovered.
   - Deduplicate projected vertices and fit only crease-shared generator vertices in [`fit_cylinder`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/fitting.py#L28); allow clipped end gaps in [`tessellation()`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/coarse.py#L28).
   - Add direct ellipse fitting (`fit_ellipse_2d`) + Menger curvature / Runs test to distinguish circular arcs, elliptical arcs (`memo_cartridge` feet `C120–C125`), and splines.
2. **Add Iterative Defeaturing (Várady/Benkő "Suppress-and-Extend") before Base-Body Detection (`fits now`):**
   - Detect 3D corner blends (< 10% area), 3D convex edge rounds, and 3D symmetric chamfers on the RAG first; record them as dress-up features, remove their faces from the RAG, and intersect/extend their adjacent host planes to restore sharp corners.
   - Emit 3D convex edge rounds and chamfers in [`emit.py`](file:///home/heratiki/Source/stl2scad/stl2scad/core/segmentation/emit.py) as negative corner-wedge cutters inside `BooleanDifference.cuts`.
3. **Generalize Single-Cap Extrusion to Multi-Height 2.5D Extrusion Barrels (`fits now`):**
   - Group remaining faces by shared extrusion axis and axial height interval $[z_a, z_b]$ (Point2Cyl barrel clustering + mid-slab slicing) so stepped parts (`memo_power_button` 2 mm bar + 10 mm head + 10 mm rib; `memo_cartridge` 2 mm plate + 5 mm feet) emit as a `BooleanUnion` of linked `ExtrudeLinear` slabs.
4. **Close Free-Form Remainder Patches via Exterior/Interior Apex Fan Closure (`fits now`):**
   - Close any unresolved surface patch (such as the 3D setback corners `F118/F119` in `memo_cartridge` and `F56` corners in `memo_power_button`) into a guaranteed-watertight 2-manifold `polyhedron` by connecting its boundary loop edges to a single offset apex point ($\mathbf{q} \pm \epsilon \sum \mathbf{n}_k$), and anchor its placement to the host planes' parameter expressions.
