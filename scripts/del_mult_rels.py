import bonsai.tool as tool
import bpy
import os

model = tool.Ifc.get()

# ---------- SETTINGS ----------
DRY_RUN = True   # First run True. After checking log, change to False.
OUTPUT_SUFFIX = "_fixed_text_leader_relations"
# ------------------------------

TARGET_CLASSES = [
    "IfcSwitchingDevice",
    "IfcOutlet",
    "IfcLightFixture",
    "IfcElectricAppliance",
    "IfcDistributionControlElement",
    "IfcFlowTerminal",
    "IfcFlowController",
]

log = bpy.data.texts.get("IFC Cleanup Log") or bpy.data.texts.new("IFC Cleanup Log")
out = bpy.data.texts.get("IFC Output") or bpy.data.texts.new("IFC Output")
log.clear()
out.clear()

def write(msg=""):
    text = str(msg) + "\n"
    log.write(text)
    out.write(text)

def is_target_product(product):
    if not product:
        return False
    return any(product.is_a(cls) for cls in TARGET_CLASSES)

# Find current IFC path
ifc_path = tool.Ifc.get_path()

if not ifc_path:
    raise Exception("Could not find current IFC file path. Please save/open the IFC file properly first.")

folder = os.path.dirname(ifc_path)
filename = os.path.basename(ifc_path)
name, ext = os.path.splitext(filename)

output_path = os.path.join(folder, name + OUTPUT_SUFFIX + ext)

problem_annotation_count = 0
edited_relation_count = 0
deleted_relation_count = 0

write("TEXT_LEADER MULTIPLE PRODUCT RELATION CLEANUP")
write("=" * 100)
write("Mode: " + ("DRY RUN - no changes saved" if DRY_RUN else "LIVE - IFC modified and saved"))
write("Current IFC: " + ifc_path)
write("Output IFC : " + output_path)
write("Target classes: " + ", ".join(TARGET_CLASSES))
write("Rule: keep LAST relation from inverse order")
write("=" * 100)

for annotation in model.by_type("IfcAnnotation"):

    if annotation.Name != "TEXT_LEADER":
        continue

    product_relations = []

    for inv in model.get_inverse(annotation):
        if inv.is_a("IfcRelAssignsToProduct"):
            product = inv.RelatingProduct
            if is_target_product(product):
                product_relations.append(inv)

    if len(product_relations) <= 1:
        continue

    problem_annotation_count += 1

    # IMPORTANT:
    # Keep the last relation from inverse order, not highest STEP id
    keep_relation = product_relations[-1]
    keep_product = keep_relation.RelatingProduct
    keep_obj = tool.Ifc.get_object(keep_product)

    write("")
    write("=" * 100)
    write("ANNOTATION WITH MULTIPLE PRODUCT RELATIONS")
    write("Annotation: " + str(annotation))
    write("Annotation GUID: " + annotation.GlobalId)
    write("Annotation STEP ID: #" + str(annotation.id()))
    write("Total product relations found: " + str(len(product_relations)))

    write("")
    write("ALL RELATIONS IN ORDER:")
    for rel in product_relations:
        product = rel.RelatingProduct
        blender_obj = tool.Ifc.get_object(product)
        write(
            "#" + str(rel.id()) +
            " -> " + product.is_a() +
            " -> Tag: " + str(getattr(product, "Tag", None)) +
            " -> Blender: " + (blender_obj.name if blender_obj else "None")
        )

    write("")
    write("KEEPING LAST RELATION")
    write("Relation: #" + str(keep_relation.id()))
    write("Product: " + str(keep_product))
    write("Product Class: " + keep_product.is_a())
    write("Tag: " + str(getattr(keep_product, "Tag", None)))
    write("Blender Object: " + (keep_obj.name if keep_obj else "None"))
    write("")

    for rel in product_relations:

        if rel == keep_relation:
            continue

        product = rel.RelatingProduct
        blender_obj = tool.Ifc.get_object(product)

        write("REMOVING OLD RELATION LINK")
        write("Old Relation: #" + str(rel.id()))
        write("Old Product: " + str(product))
        write("Old Product Class: " + product.is_a())
        write("Old Tag: " + str(getattr(product, "Tag", None)))
        write("Old Blender Object: " + (blender_obj.name if blender_obj else "None"))

        old_related = list(rel.RelatedObjects)
        new_related = [x for x in old_related if x != annotation]

        write("RelatedObjects before: " + str([x.id() for x in old_related]))
        write("RelatedObjects after : " + str([x.id() for x in new_related]))

        if not DRY_RUN:
            if len(new_related) == 0:
                model.remove(rel)
                deleted_relation_count += 1
                write("Action: Deleted entire relation because it became empty.")
            else:
                rel.RelatedObjects = tuple(new_related)
                edited_relation_count += 1
                write("Action: Removed annotation from old relation.")
        else:
            write("Action: DRY RUN only. No change made.")

        write("-" * 80)

write("")
write("=" * 100)
write("SUMMARY")
write("Problem annotations found: " + str(problem_annotation_count))
write("Relations edited: " + str(edited_relation_count))
write("Relations deleted: " + str(deleted_relation_count))

if not DRY_RUN:
    model.write(output_path)
    write("Saved fixed IFC to:")
    write(output_path)
else:
    write("DRY RUN complete. No IFC saved.")

write("=" * 100)