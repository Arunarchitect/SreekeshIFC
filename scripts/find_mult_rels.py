import bonsai.tool as tool
import bpy

log = bpy.data.texts.get("IFC Output") or bpy.data.texts.new("IFC Output")
log.clear()

def write(msg=""):
    log.write(str(msg) + "\n")

model = tool.Ifc.get()

TARGET_CLASSES = [
    "IfcSwitchingDevice",
    "IfcOutlet",
    "IfcLightFixture",
]

found_multiple = False

for annotation in model.by_type("IfcAnnotation"):

    if annotation.Name != "TEXT_LEADER":
        continue

    product_relations = []

    for inv in model.get_inverse(annotation):
        if inv.is_a("IfcRelAssignsToProduct"):
            product = inv.RelatingProduct

            if product and any(product.is_a(cls) for cls in TARGET_CLASSES):
                product_relations.append(inv)

    if len(product_relations) > 1:
        found_multiple = True

        # keeping last relation from inverse order
        latest_relation = product_relations[-1]
        product = latest_relation.RelatingProduct
        blender_obj = tool.Ifc.get_object(product)

        write("=" * 80)
        write("Annotation: " + annotation.GlobalId)
        write(annotation)
        write("Total product relations: " + str(len(product_relations)))

        write("\nALL RELATIONS IN ORDER:")
        for rel in product_relations:
            rel_product = rel.RelatingProduct
            rel_obj = tool.Ifc.get_object(rel_product)

            write(
                "#" + str(rel.id()) +
                " -> " + rel_product.is_a() +
                " -> Tag: " + str(getattr(rel_product, "Tag", None)) +
                " -> Blender: " + (rel_obj.name if rel_obj else "None")
            )

        write("\nLatest/kept relation: #" + str(latest_relation.id()))
        write("Correct/Latest product:")
        write(product)
        write("Product Class: " + product.is_a())
        write("Blender object: " + (blender_obj.name if blender_obj else "None"))
        write("")

if not found_multiple:
    write("No multiple relations found.")