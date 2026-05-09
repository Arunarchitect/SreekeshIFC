import bonsai.tool as tool
import ifcopenshell
import ifcopenshell.guid
import bpy
import os

# ---------------- SETTINGS ----------------
DRY_RUN = True  # First run True. After checking log, change to False.
FILE_B_NAME = "Sreekesh_new.ifc"
OUTPUT_SUFFIX = "13"

GUID_STRING = "3sqFYwMkH3Xwhia9Vu64Kn"

TARGET_ANNOTATION_GUIDS = [
    x.strip() for x in GUID_STRING.split(",") if x.strip()
]

TARGET_CLASSES = [
    "IfcSwitchingDevice",
    "IfcOutlet",
    "IfcLightFixture",
    "IfcElectricAppliance"
]

SOURCE_MODE = "LAST_ONLY"
# "LAST_ONLY" = copy only last product relation from File B
# "ALL"       = copy all target product relations from File B
# ------------------------------------------

model_a = tool.Ifc.get()

file_a_path = tool.Ifc.get_path()
folder = os.path.dirname(file_a_path)

file_b_path = os.path.normpath(os.path.join(folder, FILE_B_NAME))
model_b = ifcopenshell.open(file_b_path)

name, ext = os.path.splitext(os.path.basename(file_a_path))
output_path = os.path.normpath(os.path.join(folder, name + OUTPUT_SUFFIX + ext))

log = bpy.data.texts.get("IFC Output") or bpy.data.texts.new("IFC Output")
log.clear()

def write(msg=""):
    log.write(str(msg) + "\n")

def is_target_product(product):
    return product and any(product.is_a(cls) for cls in TARGET_CLASSES)

def get_target_relations(model, annotation):
    rels = []
    for inv in model.get_inverse(annotation):
        if inv.is_a("IfcRelAssignsToProduct"):
            product = inv.RelatingProduct
            if is_target_product(product):
                rels.append(inv)
    return rels

def remove_annotation_from_old_relations(model, annotation):
    for rel in list(get_target_relations(model, annotation)):
        old_related = list(rel.RelatedObjects)
        new_related = [x for x in old_related if x != annotation]

        write("Removing old A relation: #" + str(rel.id()))
        write("Old product: " + str(rel.RelatingProduct))
        write("RelatedObjects before: " + str([x.id() for x in old_related]))
        write("RelatedObjects after : " + str([x.id() for x in new_related]))

        if not DRY_RUN:
            if len(new_related) == 0:
                model.remove(rel)
                write("Action: deleted empty relation")
            else:
                rel.RelatedObjects = tuple(new_related)
                write("Action: removed annotation from relation")
        else:
            write("Action: DRY RUN only. No change made.")

        write("-" * 60)

def assign_annotation_to_product(model, annotation, product):
    existing_rel = None

    for inv in model.get_inverse(product):
        if inv.is_a("IfcRelAssignsToProduct") and inv.RelatingProduct == product:
            existing_rel = inv
            break

    if existing_rel:
        related = list(existing_rel.RelatedObjects)

        if annotation not in related:
            related.append(annotation)

            if not DRY_RUN:
                existing_rel.RelatedObjects = tuple(related)

            write("Added annotation to existing relation #" + str(existing_rel.id()))
        else:
            write("Annotation already exists in relation #" + str(existing_rel.id()))

    else:
        owner_history_list = model.by_type("IfcOwnerHistory")
        owner_history = owner_history_list[0] if owner_history_list else None

        if not DRY_RUN:
            new_rel = model.create_entity(
                "IfcRelAssignsToProduct",
                ifcopenshell.guid.new(),
                owner_history,
                None,
                None,
                (annotation,),
                None,
                product
            )
            write("Created new relation #" + str(new_rel.id()))
        else:
            write("Would create new IfcRelAssignsToProduct relation")

write("COPY TEXT_LEADER PRODUCT RELATIONS FROM FILE B TO FILE A")
write("=" * 100)
write("Mode: " + ("DRY RUN - no changes saved" if DRY_RUN else "LIVE - File A will be modified and saved"))
write("File A/current: " + file_a_path)
write("File B/source : " + file_b_path)
write("Output file   : " + output_path)
write("Source mode   : " + SOURCE_MODE)
write("Target classes: " + ", ".join(TARGET_CLASSES))
write("Target GUIDs  : " + ", ".join(TARGET_ANNOTATION_GUIDS))
write("=" * 100)

processed = 0
matched = 0
skipped_not_in_guid_list = 0
skipped_no_a_annotation = 0
skipped_no_b_annotation = 0
skipped_no_b_relation = 0
skipped_missing_product_in_a = 0

# Process only GUIDs given in GUID_STRING
for gid in TARGET_ANNOTATION_GUIDS:

    annotation_a = model_a.by_guid(gid)

    if not annotation_a:
        skipped_no_a_annotation += 1
        write("")
        write("WARNING: Annotation GUID not found in File A: " + gid)
        continue

    if not annotation_a.is_a("IfcAnnotation") or annotation_a.Name != "TEXT_LEADER":
        skipped_not_in_guid_list += 1
        write("")
        write("WARNING: GUID exists in File A, but is not TEXT_LEADER annotation: " + gid)
        write(str(annotation_a))
        continue

    processed += 1

    annotation_b = model_b.by_guid(gid)

    if not annotation_b:
        skipped_no_b_annotation += 1
        write("")
        write("WARNING: Same annotation GUID not found in File B: " + gid)
        continue

    rels_b = get_target_relations(model_b, annotation_b)

    if not rels_b:
        skipped_no_b_relation += 1
        write("")
        write("WARNING: No target product relation found in File B for: " + gid)
        continue

    if SOURCE_MODE == "LAST_ONLY":
        rels_b = [rels_b[-1]]

    write("")
    write("=" * 100)
    write("MATCHED TEXT_LEADER")
    write("Annotation GUID: " + gid)
    write("File A annotation: " + str(annotation_a))
    write("File B annotation: " + str(annotation_b))
    write("Relations copied from B: " + str(len(rels_b)))

    target_products_a = []

    for rel_b in rels_b:
        product_b = rel_b.RelatingProduct
        product_gid = product_b.GlobalId
        product_a = model_a.by_guid(product_gid)

        write("")
        write("Source B relation: #" + str(rel_b.id()))
        write("Source B product : " + str(product_b))
        write("Product GUID     : " + product_gid)

        if not product_a:
            skipped_missing_product_in_a += 1
            write("WARNING: Matching product not found in File A. Skipped.")
            continue

        write("Target A product : " + str(product_a))

        blender_obj = tool.Ifc.get_object(product_a)
        write("A Blender object : " + (blender_obj.name if blender_obj else "None"))

        target_products_a.append(product_a)

    if not target_products_a:
        continue

    write("")
    write("Cleaning old File A product relations for this annotation...")
    remove_annotation_from_old_relations(model_a, annotation_a)

    write("")
    write("Creating/copying File B relations into File A...")
    for product_a in target_products_a:
        assign_annotation_to_product(model_a, annotation_a, product_a)

    matched += 1

write("")
write("=" * 100)
write("SUMMARY")
write("Target GUIDs given             : " + str(len(TARGET_ANNOTATION_GUIDS)))
write("TEXT_LEADER annotations checked: " + str(processed))
write("Annotations updated/matched    : " + str(matched))
write("GUID not found in File A       : " + str(skipped_no_a_annotation))
write("Not TEXT_LEADER in File A      : " + str(skipped_not_in_guid_list))
write("No same annotation in File B   : " + str(skipped_no_b_annotation))
write("No product relation in File B  : " + str(skipped_no_b_relation))
write("Missing product in File A      : " + str(skipped_missing_product_in_a))

if not DRY_RUN:
    model_a.write(output_path)
    write("Saved fixed File A to:")
    write(output_path)
else:
    write("DRY RUN complete. No file saved.")

write("=" * 100)