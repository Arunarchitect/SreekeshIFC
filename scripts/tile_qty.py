"""
tile_quantity_takeoff.py
-------------------------------------------------------------------------
Counts tiles (full / three-quarter / half / quarter / sliver / opening-
affected) as they are ACTUALLY rendered by a Blender ShaderNodeTexBrick,
for the currently SELECTED IfcCovering wall tile object(s). Intended as
a BOQ cross-check against IfcCoveringBase area quantities (which include
waste and hide the real cut-tile count).

Run this in Blender's Scripting tab / Text Editor. Select one or more
mesh objects in the 3D Viewport first (multi-select is fine — the
report will break totals down per object and give a grand total).

No object name or material name needs to be typed in: the script reads
whatever is selected, and on each object it auto-detects every material
slot whose material contains a Brick Texture node (ShaderNodeTexBrick)
feeding a Mapping node. Objects/materials with no brick texture are
skipped automatically.

OUTPUT: the full report is written into a Blender Text datablock
(Text Editor) named "Tile Takeoff Report" and that Text Editor area is
switched to show it, so you see it right inside Blender's UI. Nothing
is written to disk.

CUT-ORIENTATION CLASSIFICATION (cells NOT touched by an opening)
  A cut cell that doesn't overlap an opening is only ever trimmed along
  the brick grid's u-axis (a vertical cut, i.e. the tile keeps its full
  row height but loses width off one side) or its v-axis (a horizontal
  cut, i.e. it keeps full width but loses height off the top/bottom of
  a row), or, at a panel corner, both at once. So each such piece is
  tagged:
    - "<size>_vertical"   : full height retained, width is <size>
    - "<size>_horizontal" : full width retained, height is <size>
    - "corner"            : both axes clipped by the panel boundary
  where <size> is three_quarter / half / quarter / sliver, based on how
  much of the relevant axis survives.

OPENING (IfcOpeningElement / window / door VOID) HANDLING - NEW
  IfcOpeningElement voids show up in the imported mesh as an actual
  hole cut into the wall panel (the boolean has already been applied
  by the time it's geometry in Blender). That hole is an INNER edge
  loop inside the island, in addition to the island's OUTER edge loop.

  For every material island, the script:
    1. Collects every "boundary edge" of the island — an edge with
       exactly one of its linked faces inside the island's face set.
       For a plain closed panel with no holes this traces just the
       outer silhouette. For a panel with a window/door cut into it,
       it also traces one closed loop per hole.
    2. Walks those boundary edges into closed vertex loops.
    3. Maps each loop into the same (u, v) brick-texture space as
       everything else, and ranks loops by polygon area (shoelace
       formula). The largest-area loop is treated as the panel's
       OUTER boundary; every other loop is treated as an OPENING.
       Loops smaller than HOLE_MIN_AREA_FRACTION of the outer loop's
       area are discarded as noise (sliver internal edges, etc).
    4. Each opening loop is reduced to its axis-aligned (u, v)
       bounding rectangle — i.e. openings are assumed rectangular,
       same simplifying assumption the rest of the script already
       makes for panel shape. This is a good match for real
       IfcOpeningElement voids (windows/doors), which are rectangular
       the overwhelming majority of the time.
    5. When the brick grid is re-derived, every cell is first clipped
       to the panel's real (u, v) extent as before, and THEN each
       opening rectangle is subtracted from that clipped cell:
         - cell entirely inside an opening -> no tile piece at all
           (it's genuinely empty wall, not tile).
         - cell not touching any opening -> classified exactly as
           before (full / vertical / horizontal / corner).
         - cell partially overlapping an opening -> bucketed as
           "opening_affected". Its net (post-subtraction) area is
           reported, but the script deliberately does NOT try to
           classify the leftover L/U-shaped remnant as a simple
           vertical/horizontal/corner cut fraction — see LIMITATIONS.
    6. Each island's detected openings are also listed by themselves
       (approx width x height, m2) so you can eyeball them against
       the actual IfcOpeningElement dimensions from your IFC model as
       a sanity check that the hole was picked up correctly.

LIMITATIONS (please read before trusting the numbers)
  - Each island's OUTER boundary is treated as its bounding rectangle
    in (u,v) space, same as before. For a plain rectangular wall panel
    this is exact. For an L-shaped panel, the script will still
    overcount along the panel boundary — that limitation is unchanged
    and is separate from opening handling.
  - Openings are reduced to their axis-aligned bounding rectangle. A
    non-rectangular opening (e.g. an arched-top doorway) will be
    slightly overcounted as void (i.e. slightly UNDERCOUNTED as tile),
    conservative in the "don't over-order" direction is NOT guaranteed
    either way — check unusually-shaped openings by eye.
  - "opening_affected" pieces are reported as a count + net area only.
    Since subtracting a rectangle from a tile cell generally leaves an
    L or U shaped remnant (not a simple straight cut), the script does
    NOT attempt to bin-pack these against each other or against
    plain vertical/horizontal offcuts — each is conservatively quoted
    as needing its own source tile. Review these by eye; a real
    installer may be able to cut several from one tile.
  - Two overlapping openings on the same island (rare in practice) are
    handled by summing their individual overlap areas per cell without
    de-duplicating the double-covered region, which can slightly
    under-count net tile area in that specific overlap zone.
  - Boundary-loop tracing is best-effort on non-manifold geometry
    (e.g. an internal edge with more than 2 linked faces, or a
    partially-merged mesh). If a wall's opening count looks wrong,
    check the mesh with Select > Non-Manifold in Edit Mode first.
  - Mortar Size/Smooth only affect the antialiased visual edge of a
    tile, not which grid cell a point belongs to, so they're not used
    for counting (they don't change how many tiles there are).
  - Object scale (obj.scale) is intentionally NOT applied: the Brick
    Texture node computes its grid on local mesh coordinates before the
    object transform, so counts are correct regardless of object scale.
  - If your counts look transposed (e.g. way too many rows, too few
    columns) your wall's local axes don't match the U_AXIS/V_AXIS
    assumption below -- flip them (see CONFIG).
  - The tile-reuse packing (for plain vertical/horizontal offcuts) is
    1-D per orientation group. It doesn't try to nest a vertical
    offcut against a horizontal offcut, or against opening-affected
    or corner pieces. Treat the "recommended purchase quantity" as a
    good, safe estimate, not a cutting plan.
-------------------------------------------------------------------------
"""

import bpy
import bmesh
import math
from mathutils import Euler
from collections import defaultdict

# ======================= CONFIG - edit these =======================

# After the Mapping node's transform is applied, which mapped axis is
# the brick "column" (width) direction and which is "row" (height)?
# Default matches standard usage: mapped X = width, mapped Y = height.
# If results look transposed, swap these to 'y' / 'x'.
U_AXIS = 'x'
V_AXIS = 'y'

# Classification thresholds, as a fraction of one full tile's WIDTH
# (for vertical cuts) or HEIGHT (for horizontal cuts) that survives
# being clipped to the wall's real extent.
FULL_THRESH          = 0.97
THREE_QUARTER_LOW    = 0.70
HALF_LOW, HALF_HIGH   = 0.40, 0.60
QUARTER_LOW, QUARTER_HIGH = 0.15, 0.35

# An inner boundary loop on an island is only treated as a real opening
# (window/door void) if its (u,v) polygon area is at least this fraction
# of the island's outer-loop area. Filters out tiny non-manifold /
# stray-edge loops that aren't actual IfcOpeningElement voids.
HOLE_MIN_AREA_FRACTION = 0.002

REPORT_TEXT_NAME = "Tile Takeoff Report"

# =====================================================================


def find_node(node_tree, bl_idname):
    for n in node_tree.nodes:
        if n.bl_idname == bl_idname:
            return n
    return None


def find_brick_materials(obj):
    """Yields (slot_index, material, brick_node, mapping_node) for every
    material slot on obj whose material has a Brick Texture node fed by
    a Mapping node. Materials without both are skipped silently."""
    for i, slot in enumerate(obj.material_slots):
        mat = slot.material
        if mat is None or mat.node_tree is None:
            continue
        brick_node = find_node(mat.node_tree, 'ShaderNodeTexBrick')
        mapping_node = find_node(mat.node_tree, 'ShaderNodeMapping')
        if brick_node is not None and mapping_node is not None:
            yield i, mat, brick_node, mapping_node


def get_mapping_transform(mapping_node):
    """Returns a function mapping a local Vector -> mapped Vector,
    replicating the Mapping node's Point transform:
        result = Rotation @ (vector * scale) + location
    """
    loc = mapping_node.inputs['Location'].default_value
    rot = mapping_node.inputs['Rotation'].default_value
    scl = mapping_node.inputs['Scale'].default_value
    rot_mat = Euler((rot[0], rot[1], rot[2]), 'XYZ').to_matrix()

    def transform(vec):
        scaled = vec.copy()
        scaled.x *= scl[0]
        scaled.y *= scl[1]
        scaled.z *= scl[2]
        rotated = rot_mat @ scaled
        return rotated + loc

    return transform


def get_brick_params(brick_node):
    return {
        'brick_width': brick_node.inputs['Brick Width'].default_value,
        'row_height':  brick_node.inputs['Row Height'].default_value,
        'scale':       brick_node.inputs['Scale'].default_value,
        # node properties, not sockets:
        'offset':           brick_node.offset,
        'offset_frequency': brick_node.offset_frequency,
        'squash':           brick_node.squash,
        'squash_frequency': brick_node.squash_frequency,
    }


def get_material_islands(obj, slot_index):
    """Yields lists of bmesh faces, one list per connected island of
    faces that use the given material slot index on this object."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    target_faces = {f for f in bm.faces if f.material_index == slot_index}
    visited = set()
    islands = []

    for seed in target_faces:
        if seed in visited:
            continue
        island = []
        stack = [seed]
        visited.add(seed)
        while stack:
            f = stack.pop()
            island.append(f)
            for e in f.edges:
                for lf in e.link_faces:
                    if lf in target_faces and lf not in visited:
                        visited.add(lf)
                        stack.append(lf)
        islands.append(island)

    return bm, islands


def get_boundary_edges(island_faces):
    """Returns the edges that border the given island on exactly one
    side (either a true mesh boundary, or a boundary against faces
    outside this island/material). These edges trace the island's
    outer silhouette PLUS one closed loop per interior hole (window /
    door opening) cut into it."""
    island_set = set(island_faces)
    boundary = []
    seen = set()
    for f in island_faces:
        for e in f.edges:
            if e in seen:
                continue
            seen.add(e)
            linked_in_island = sum(1 for lf in e.link_faces if lf in island_set)
            if linked_in_island == 1:
                boundary.append(e)
    return boundary


def trace_loops(boundary_edges):
    """Best-effort walk of boundary edges into closed vertex loops.
    Returns a list of vertex lists (one per loop). Non-manifold
    boundary edges (a vertex touched by more than 2 boundary edges)
    are handled by just taking the first unvisited edge at each step;
    on clean 2-manifold geometry (the normal case for an IFC-imported
    wall panel) this produces exact loops."""
    edge_set = set(boundary_edges)
    v_edges = defaultdict(list)
    for e in edge_set:
        v_edges[e.verts[0]].append(e)
        v_edges[e.verts[1]].append(e)

    visited = set()
    loops = []

    for start_e in edge_set:
        if start_e in visited:
            continue
        visited.add(start_e)
        loop_start_v = start_e.verts[0]
        loop_verts = [loop_start_v]
        current_v = start_e.verts[1]
        safety = 0
        max_steps = len(edge_set) + 1
        while current_v != loop_start_v and safety < max_steps:
            safety += 1
            loop_verts.append(current_v)
            candidates = [e for e in v_edges[current_v] if e not in visited]
            if not candidates:
                break  # open/non-manifold chain - stop, best effort
            next_e = candidates[0]
            visited.add(next_e)
            current_v = next_e.verts[0] if next_e.verts[1] == current_v else next_e.verts[1]
        loops.append(loop_verts)
    return loops


def loop_uv_bbox_and_area(loop_verts, to_mapped):
    """Maps a closed vertex loop into (u,v) space and returns its
    axis-aligned bounding box plus its polygon area (shoelace)."""
    pts = [to_mapped(v.co) for v in loop_verts]
    us = [getattr(p, U_AXIS) for p in pts]
    vs = [getattr(p, V_AXIS) for p in pts]
    u_min, u_max = min(us), max(us)
    v_min, v_max = min(vs), max(vs)

    area = 0.0
    n = len(pts)
    if n >= 3:
        for i in range(n):
            x1, y1 = us[i], vs[i]
            x2, y2 = us[(i + 1) % n], vs[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        area = abs(area) / 2.0

    return {'u_min': u_min, 'u_max': u_max, 'v_min': v_min, 'v_max': v_max, 'area': area}


def find_island_openings(island_faces, to_mapped):
    """Returns (outer_bbox, opening_rects). outer_bbox is the (u,v)
    bounding box of the island's largest boundary loop (the panel's
    outer silhouette). opening_rects is a list of (u,v) bounding
    rectangles for every other boundary loop big enough to not be
    noise - i.e. the detected window/door voids."""
    boundary_edges = get_boundary_edges(island_faces)
    loops = trace_loops(boundary_edges)

    boxes = [loop_uv_bbox_and_area(lv, to_mapped) for lv in loops if len(lv) >= 3]
    if not boxes:
        return None, []

    boxes.sort(key=lambda b: b['area'], reverse=True)
    outer = boxes[0]
    holes = [b for b in boxes[1:] if b['area'] >= HOLE_MIN_AREA_FRACTION * outer['area']]
    return outer, holes


def enumerate_tiles(u_min, u_max, v_min, v_max, params, holes=None):
    """Re-derives the brick grid and clips each cell against the
    panel's real (u,v) extent, then against every opening rectangle in
    `holes`. Returns one dict per surviving (non-zero-area) piece."""
    holes = holes or []
    bw = params['brick_width'] / params['scale']
    rh = params['row_height'] / params['scale']
    offset, offset_freq = params['offset'], int(params['offset_frequency'])
    squash, squash_freq = params['squash'], int(params['squash_frequency'])

    tiles = []
    row_start = math.floor(v_min / rh)
    row_end = math.floor((v_max - 1e-9) / rh)

    for row in range(row_start, row_end + 1):
        v0, v1 = row * rh, (row + 1) * rh
        ov_v0, ov_v1 = max(v0, v_min), min(v1, v_max)
        if ov_v1 <= ov_v0:
            continue

        x_shift = bw * offset if (offset_freq > 0 and row % offset_freq != 0) else 0.0
        bw_row = bw * squash if (squash_freq > 0 and row % squash_freq != 0) else bw

        col_start = math.floor((u_min + x_shift) / bw_row)
        col_end = math.floor((u_max + x_shift - 1e-9) / bw_row)

        for col in range(col_start, col_end + 1):
            cu0 = col * bw_row - x_shift
            cu1 = cu0 + bw_row
            ov_u0, ov_u1 = max(cu0, u_min), min(cu1, u_max)
            if ov_u1 <= ov_u0:
                continue

            u_frac = (ov_u1 - ov_u0) / bw_row
            v_frac = (ov_v1 - ov_v0) / rh
            cell_area = (ov_u1 - ov_u0) * (ov_v1 - ov_v0)

            hole_overlap_area = 0.0
            touched_holes = 0
            for h in holes:
                hu0, hu1 = max(ov_u0, h['u_min']), min(ov_u1, h['u_max'])
                hv0, hv1 = max(ov_v0, h['v_min']), min(ov_v1, h['v_max'])
                if hu1 > hu0 and hv1 > hv0:
                    hole_overlap_area += (hu1 - hu0) * (hv1 - hv0)
                    touched_holes += 1

            net_area = cell_area - hole_overlap_area
            if net_area <= 1e-9:
                continue  # cell is entirely inside an opening - no tile here

            tiles.append({
                'row': row, 'col': col,
                'u_frac': u_frac, 'v_frac': v_frac,
                'coverage': u_frac * v_frac,
                'tile_area_full': bw_row * rh,
                'tile_area_clipped': cell_area,
                'hole_overlap_area': hole_overlap_area,
                'touched_holes': touched_holes,
                'net_area': net_area,
            })
    return tiles


def size_name(frac):
    if frac >= THREE_QUARTER_LOW:
        return 'three_quarter'
    if HALF_LOW <= frac <= HALF_HIGH:
        return 'half'
    if QUARTER_LOW <= frac <= QUARTER_HIGH:
        return 'quarter'
    if frac < QUARTER_LOW:
        return 'sliver'
    return 'other'


def classify_piece(u_frac, v_frac):
    """Returns (bucket_name, orientation, size_frac) for a piece that
    does NOT touch any opening. orientation is 'vertical' or
    'horizontal' for single-axis cuts (size_frac is the surviving
    fraction of that axis, used later for tile-reuse packing), or None
    for 'full' / 'corner' pieces."""
    full_u = u_frac >= FULL_THRESH
    full_v = v_frac >= FULL_THRESH

    if full_u and full_v:
        return 'full', None, None
    if full_v and not full_u:
        return f'{size_name(u_frac)}_vertical', 'vertical', u_frac
    if full_u and not full_v:
        return f'{size_name(v_frac)}_horizontal', 'horizontal', v_frac
    return 'corner', None, None


def bin_pack_count(fracs, capacity=1.0):
    """First-fit-decreasing bin packing. Returns number of bins (source
    tiles) needed to cut every fraction in `fracs` out of tiles of the
    given capacity (1.0 = one full tile's width or height)."""
    bins = []
    for f in sorted(fracs, reverse=True):
        placed = False
        for i in range(len(bins)):
            if bins[i] + f <= capacity + 1e-6:
                bins[i] += f
                placed = True
                break
        if not placed:
            bins.append(f)
    return len(bins)


def analyse_object_material(obj, slot_index, mat, brick_node, mapping_node, lines):
    params = get_brick_params(brick_node)
    to_mapped = get_mapping_transform(mapping_node)

    bm, islands = get_material_islands(obj, slot_index)

    all_pieces = []
    island_summaries = []
    all_openings = []  # (island_idx, opening_bbox_dict) for reporting

    for idx, island in enumerate(islands):
        verts = {v for f in island for v in f.verts}
        mapped = [to_mapped(v.co) for v in verts]
        us = [getattr(m, U_AXIS) for m in mapped]
        vs = [getattr(m, V_AXIS) for m in mapped]
        u_min, u_max = min(us), max(us)
        v_min, v_max = min(vs), max(vs)

        outer_bbox, holes = find_island_openings(island, to_mapped)
        for h in holes:
            all_openings.append((idx, h))

        tiles = enumerate_tiles(u_min, u_max, v_min, v_max, params, holes=holes)
        for t in tiles:
            if t['touched_holes'] > 0:
                t['bucket'] = 'opening_affected'
                t['orientation'] = None
                t['size_frac'] = None
            else:
                bucket, orientation, size_frac = classify_piece(t['u_frac'], t['v_frac'])
                t['bucket'] = bucket
                t['orientation'] = orientation
                t['size_frac'] = size_frac
            t['island'] = idx
        all_pieces.extend(tiles)

        wall_area = (u_max - u_min) * (v_max - v_min)
        opening_area = sum((h['u_max'] - h['u_min']) * (h['v_max'] - h['v_min']) for h in holes)
        island_summaries.append({
            'island': idx, 'faces': len(island),
            'width': u_max - u_min, 'height': v_max - v_min,
            'area': wall_area,
            'openings': len(holes),
            'opening_area': opening_area,
        })

    bm.free()

    counts = defaultdict(int)
    for t in all_pieces:
        counts[t['bucket']] += 1

    total_pieces = len(all_pieces)
    equivalent_full_tiles = sum(t['coverage'] for t in all_pieces)
    total_covered_area = sum(t['tile_area_clipped'] for t in all_pieces)
    total_net_area = sum(t['net_area'] for t in all_pieces)
    total_wall_area = sum(s['area'] for s in island_summaries)
    total_opening_area = sum(s['opening_area'] for s in island_summaries)

    full_count = counts.get('full', 0)
    corner_count = counts.get('corner', 0)
    opening_affected_count = counts.get('opening_affected', 0)
    vertical_fracs = [t['size_frac'] for t in all_pieces if t['orientation'] == 'vertical']
    horizontal_fracs = [t['size_frac'] for t in all_pieces if t['orientation'] == 'horizontal']

    tiles_needed_vertical = bin_pack_count(vertical_fracs)
    tiles_needed_horizontal = bin_pack_count(horizontal_fracs)

    naive_cut_tiles = len(vertical_fracs) + len(horizontal_fracs) + corner_count + opening_affected_count
    optimized_cut_tiles = tiles_needed_vertical + tiles_needed_horizontal + corner_count + opening_affected_count
    saved_tiles = naive_cut_tiles - optimized_cut_tiles

    recommended_purchase = full_count + optimized_cut_tiles

    lines.append("-" * 60)
    lines.append(f"OBJECT: {obj.name}   MATERIAL: {mat.name}")
    lines.append("-" * 60)
    lines.append(f"Islands (separate tiled panels): {len(islands)}")
    for s in island_summaries:
        lines.append(f"  island {s['island']}: {s['faces']} faces, "
                      f"{s['width']:.4f} x {s['height']:.4f} m, area {s['area']:.4f} m2, "
                      f"openings detected: {s['openings']} "
                      f"(void area ~{s['opening_area']:.4f} m2)")

    if all_openings:
        lines.append("")
        lines.append("  Detected openings (cross-check vs. IfcOpeningElement dims):")
        for idx, h in all_openings:
            w = h['u_max'] - h['u_min']
            hgt = h['v_max'] - h['v_min']
            lines.append(f"    island {idx}: opening ~{w:.4f} x {hgt:.4f} m "
                          f"(area {h['area']:.4f} m2)")

    lines.append("")
    lines.append("  Piece counts (by size and cut orientation):")
    order = [
        'full',
        'three_quarter_vertical', 'three_quarter_horizontal',
        'half_vertical', 'half_horizontal',
        'quarter_vertical', 'quarter_horizontal',
        'sliver_vertical', 'sliver_horizontal',
        'corner', 'opening_affected', 'other',
    ]
    for b in order:
        if counts.get(b):
            lines.append(f"    {b:26s}: {counts[b]:5d}")
    lines.append(f"    {'TOTAL PIECES':26s}: {total_pieces:5d}")

    lines.append("")
    lines.append("  Tile-reuse packing (offcuts of the same cut orientation nested "
                  "into shared source tiles):")
    lines.append(f"    vertical-cut pieces  : {len(vertical_fracs)} piece(s) -> "
                  f"{tiles_needed_vertical} source tile(s) needed")
    lines.append(f"    horizontal-cut pieces: {len(horizontal_fracs)} piece(s) -> "
                  f"{tiles_needed_horizontal} source tile(s) needed")
    lines.append(f"    corner pieces        : {corner_count} piece(s) -> "
                  f"{corner_count} source tile(s) needed (not nestable, 1 each)")
    lines.append(f"    opening-affected pcs : {opening_affected_count} piece(s) -> "
                  f"{opening_affected_count} source tile(s) needed (irregular L/U cut, "
                  f"not nestable, 1 each - review by eye)")
    lines.append(f"    tiles saved by pairing offcuts vs. 1 new tile per cut piece: "
                  f"{saved_tiles}")

    lines.append("")
    lines.append(f"  Full (uncut) tiles needed      : {full_count}")
    lines.append(f"  Additional tiles needed for cuts: {optimized_cut_tiles}")
    lines.append(f"  >>> RECOMMENDED PURCHASE QTY   : {recommended_purchase} tiles")
    lines.append("")
    lines.append(f"  Equivalent full tiles (by area) : {equivalent_full_tiles:.2f}  "
                 f"(sum of coverage fractions - raw material quantity, no waste factor)")
    lines.append(f"  Covered area (tiles, pre-void)   : {total_covered_area:.4f} m2")
    lines.append(f"  Covered area (tiles, net of voids): {total_net_area:.4f} m2  "
                 f"<- use this one once openings exist")
    lines.append(f"  Wall area (bbox)                : {total_wall_area:.4f} m2   "
                 f"<- sanity-check this against IfcCoveringBase area")
    lines.append(f"  Opening/void area (bbox approx) : {total_opening_area:.4f} m2   "
                 f"<- sanity-check this against your IfcOpeningElement sizes")
    lines.append("")

    return {
        'counts': counts,
        'total_pieces': total_pieces,
        'equivalent_full_tiles': equivalent_full_tiles,
        'covered_area': total_covered_area,
        'net_area': total_net_area,
        'wall_area': total_wall_area,
        'opening_area': total_opening_area,
        'full_count': full_count,
        'corner_count': corner_count,
        'opening_affected_count': opening_affected_count,
        'vertical_fracs': vertical_fracs,
        'horizontal_fracs': horizontal_fracs,
        'recommended_purchase': recommended_purchase,
    }


def write_report_to_text_editor(text_str):
    """Writes text_str into a Blender Text datablock and switches any
    visible Text Editor area to display it, so the report shows up in
    Blender's UI instead of the system console."""
    txt = bpy.data.texts.get(REPORT_TEXT_NAME)
    if txt is None:
        txt = bpy.data.texts.new(REPORT_TEXT_NAME)
    txt.clear()
    txt.write(text_str)

    switched = False
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'TEXT_EDITOR':
                for space in area.spaces:
                    if space.type == 'TEXT_EDITOR':
                        space.text = txt
                        switched = True

    if not switched:
        # No Text Editor area currently open - flip the largest area
        # temporarily so the user actually sees the result.
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ('VIEW_3D', 'PROPERTIES'):
                    area.type = 'TEXT_EDITOR'
                    for space in area.spaces:
                        if space.type == 'TEXT_EDITOR':
                            space.text = txt
                    switched = True
                    break
            if switched:
                break

    return txt


def run():
    selected = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    if not selected:
        raise RuntimeError("No mesh objects selected. Select one or more "
                            "IfcCovering objects in the 3D Viewport first.")

    lines = []

    lines.append("=" * 60)
    lines.append("TILE TAKEOFF - SELECTED OBJECTS (with opening/void handling)")
    lines.append("=" * 60)
    lines.append(f"Objects selected: {len(selected)}")
    lines.append("")

    grand_counts = defaultdict(int)
    grand_total_pieces = 0
    grand_equiv = 0.0
    grand_covered_area = 0.0
    grand_net_area = 0.0
    grand_wall_area = 0.0
    grand_opening_area = 0.0
    grand_full_count = 0
    grand_corner_count = 0
    grand_opening_affected_count = 0
    grand_vertical_fracs = []
    grand_horizontal_fracs = []
    any_material_found = False

    for obj in selected:
        brick_mats = list(find_brick_materials(obj))
        if not brick_mats:
            lines.append(f"(skipped) {obj.name}: no material with a Brick "
                          f"Texture node found on this object.")
            lines.append("")
            continue

        for slot_index, mat, brick_node, mapping_node in brick_mats:
            any_material_found = True
            result = analyse_object_material(
                obj, slot_index, mat, brick_node, mapping_node, lines)

            for b, c in result['counts'].items():
                grand_counts[b] += c
            grand_total_pieces += result['total_pieces']
            grand_equiv += result['equivalent_full_tiles']
            grand_covered_area += result['covered_area']
            grand_net_area += result['net_area']
            grand_wall_area += result['wall_area']
            grand_opening_area += result['opening_area']
            grand_full_count += result['full_count']
            grand_corner_count += result['corner_count']
            grand_opening_affected_count += result['opening_affected_count']
            grand_vertical_fracs.extend(result['vertical_fracs'])
            grand_horizontal_fracs.extend(result['horizontal_fracs'])

    lines.append("=" * 60)
    lines.append("GRAND TOTAL (all selected objects / materials)")
    lines.append("=" * 60)
    if any_material_found:
        order = [
            'full',
            'three_quarter_vertical', 'three_quarter_horizontal',
            'half_vertical', 'half_horizontal',
            'quarter_vertical', 'quarter_horizontal',
            'sliver_vertical', 'sliver_horizontal',
            'corner', 'opening_affected', 'other',
        ]
        for b in order:
            if grand_counts.get(b):
                lines.append(f"  {b:26s}: {grand_counts[b]:5d}")
        lines.append(f"  {'TOTAL PIECES':26s}: {grand_total_pieces:5d}")

        # Re-pack the grand offcut pools together, since a vertical
        # offcut from one wall can, in principle, be nested with a
        # vertical offcut from another wall on the same source tile.
        # Opening-affected and corner pieces stay 1-per-tile (see
        # LIMITATIONS in the module docstring).
        grand_tiles_vertical = bin_pack_count(grand_vertical_fracs)
        grand_tiles_horizontal = bin_pack_count(grand_horizontal_fracs)
        grand_optimized_cut_tiles = (grand_tiles_vertical + grand_tiles_horizontal
                                      + grand_corner_count + grand_opening_affected_count)
        grand_recommended_purchase = grand_full_count + grand_optimized_cut_tiles

        lines.append("")
        lines.append(f"  Full (uncut) tiles needed       : {grand_full_count}")
        lines.append(f"  Vertical-cut pieces -> tiles    : {len(grand_vertical_fracs)} -> {grand_tiles_vertical}")
        lines.append(f"  Horizontal-cut pieces -> tiles  : {len(grand_horizontal_fracs)} -> {grand_tiles_horizontal}")
        lines.append(f"  Corner pieces -> tiles          : {grand_corner_count} -> {grand_corner_count}")
        lines.append(f"  Opening-affected pcs -> tiles   : {grand_opening_affected_count} -> {grand_opening_affected_count}")
        lines.append(f"  >>> RECOMMENDED PURCHASE QTY    : {grand_recommended_purchase} tiles")
        lines.append("")
        lines.append(f"  Equivalent full tiles (by area) : {grand_equiv:.2f}")
        lines.append(f"  Covered area (tiles, pre-void)   : {grand_covered_area:.4f} m2")
        lines.append(f"  Covered area (tiles, net of voids): {grand_net_area:.4f} m2")
        lines.append(f"  Wall area (bbox)                : {grand_wall_area:.4f} m2")
        lines.append(f"  Opening/void area (bbox approx) : {grand_opening_area:.4f} m2")
    else:
        lines.append("  No brick-textured materials found on any selected object.")
    lines.append("=" * 60)

    report_str = "\n".join(lines)

    txt = write_report_to_text_editor(report_str)
    print(f"Tile takeoff report written to Text Editor datablock '{txt.name}'")


if __name__ == "__main__":
    run()