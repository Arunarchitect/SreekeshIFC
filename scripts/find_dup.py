import bonsai.tool as tool
import bpy

model = tool.Ifc.get()

log = bpy.data.texts.get("IFC Output") or bpy.data.texts.new("IFC Output")
log.clear()

def write(msg=""):
    log.write(str(msg) + "\n")

def entity_signature(entity, visited=None):
    if visited is None:
        visited = set()

    if entity is None:
        return None
    if isinstance(entity, (str, int, float, bool)):
        return entity
    if isinstance(entity, (list, tuple)):
        return tuple(entity_signature(x, visited) for x in entity)
    if not hasattr(entity, "is_a"):
        return str(entity)

    if entity.id() in visited:
        return ("REF", entity.is_a())

    visited.add(entity.id())

    return (
        entity.is_a(),
        tuple(entity_signature(value, visited) for value in entity)
    )

def get_geometry_signature(annotation):
    rep = getattr(annotation, "Representation", None)
    if not rep:
        return None
    return entity_signature(rep)

def get_placement_signature(annotation):
    placement = getattr(annotation, "ObjectPlacement", None)
    if not placement:
        return None
    return entity_signature(placement)

def get_group_names(obj):
    groups = []

    for inv in model.get_inverse(obj):
        if inv.is_a("IfcRelAssignsToGroup"):
            group = inv.RelatingGroup
            groups.append(str(getattr(group, "Name", None)))

    return groups if groups else ["NO GROUP"]

def get_product_summary(obj):
    products = []

    for inv in model.get_inverse(obj):
        if inv.is_a("IfcRelAssignsToProduct"):
            product = inv.RelatingProduct
            blender_obj = tool.Ifc.get_object(product)

            products.append(
                product.is_a()
                + " | Tag: " + str(getattr(product, "Tag", None))
                + " | Blender: " + (blender_obj.name if blender_obj else "None")
            )

    return products if products else ["No Product Assignment"]

grouped = {}

for annotation in model.by_type("IfcAnnotation"):

    if annotation.Name != "TEXT_LEADER":
        continue

    geometry_sig = get_geometry_signature(annotation)
    placement_sig = get_placement_signature(annotation)

    if geometry_sig is None or placement_sig is None:
        continue

    full_signature = (geometry_sig, placement_sig)

    for group_name in get_group_names(annotation):
        key = (group_name, full_signature)
        grouped.setdefault(key, []).append(annotation)

report_by_group = {}

for (group_name, sig), annotations in grouped.items():
    if len(annotations) > 1:
        report_by_group.setdefault(group_name, []).append(annotations)

write("TEXT_LEADER DUPLICATES INSIDE EACH GROUP")
write("=" * 100)
write("Rule: exact same geometry + exact same position/rotation/object placement")
write("Tolerance: 0")
write("Checked only within the same group/drawing")
write("=" * 100)

total_duplicate_sets = 0
total_duplicate_annotations = 0

for group_name in sorted(report_by_group.keys()):

    duplicate_sets = report_by_group[group_name]
    group_duplicate_annotation_count = sum(len(x) for x in duplicate_sets)

    write("")
    write("=" * 100)
    write("GROUP: " + group_name)
    write("Duplicate sets: " + str(len(duplicate_sets)))
    write("Duplicate TEXT_LEADER count: " + str(group_duplicate_annotation_count))
    write("=" * 100)

    for index, annotations in enumerate(duplicate_sets, start=1):
        total_duplicate_sets += 1
        total_duplicate_annotations += len(annotations)

        write("")
        write("Duplicate Set " + str(index) + " | Count: " + str(len(annotations)))
        write("-" * 80)

        for annotation in annotations:
            write("GUID: " + annotation.GlobalId + " | STEP: #" + str(annotation.id()))

            for p in get_product_summary(annotation):
                write("  Assigned: " + p)

        write("-" * 80)

write("")
write("=" * 100)
write("SUMMARY")
write("Groups with duplicates          : " + str(len(report_by_group)))
write("Duplicate sets inside groups    : " + str(total_duplicate_sets))
write("Duplicate TEXT_LEADER total     : " + str(total_duplicate_annotations))

if not report_by_group:
    write("No duplicate TEXT_LEADER found with same geometry + placement inside the same group.")

write("=" * 100)