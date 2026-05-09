import bonsai.tool as tool
import bpy

model = tool.Ifc.get()

log = bpy.data.texts.get("IFC Output") or bpy.data.texts.new("IFC Output")
log.clear()

def write(msg=""):
    log.write(str(msg) + "\n")

GUID_STRING = "2BpyirL$f6vuCuR_mweUND,0fmV3XqO13wvlJE7sf_xmm"

GUIDS = [
    x.strip() for x in GUID_STRING.split(",") if x.strip()
]

for gid in GUIDS:

    write("")
    write("=" * 100)

    obj = model.by_guid(gid)

    if not obj:
        write("No IFC object found for GUID: " + gid)
        continue

    write("IFC OBJECT DETAILS")
    write("=" * 80)
    write("Object: " + str(obj))
    write("GUID: " + str(getattr(obj, "GlobalId", None)))
    write("STEP ID: #" + str(obj.id()))
    write("Class: " + obj.is_a())
    write("Name: " + str(getattr(obj, "Name", None)))
    write("Description: " + str(getattr(obj, "Description", None)))
    write("ObjectType: " + str(getattr(obj, "ObjectType", None)))
    write("PredefinedType: " + str(getattr(obj, "PredefinedType", None)))
    write("Tag: " + str(getattr(obj, "Tag", None)))

    blender_obj = tool.Ifc.get_object(obj)

    write("")
    write("BLENDER OBJECT")
    write("Name: " + (blender_obj.name if blender_obj else "None"))

    write("")
    write("INVERSE RELATIONS / GROUPS")
    write("=" * 80)

    for inv in model.get_inverse(obj):

        write("")
        write(inv)

        if inv.is_a("IfcRelAssignsToGroup"):
            group = inv.RelatingGroup

            write("  GROUP:")
            write("  " + str(group))
            write("  Group Name: " + str(getattr(group, "Name", None)))
            write("  Group Class: " + group.is_a())

        if inv.is_a("IfcRelAssignsToProduct"):
            product = inv.RelatingProduct
            product_obj = tool.Ifc.get_object(product)

            write("  ASSIGNED TO PRODUCT:")
            write("  " + str(product))
            write("  Product Class: " + product.is_a())
            write("  Product Name: " + str(getattr(product, "Name", None)))
            write("  Product Tag: " + str(getattr(product, "Tag", None)))
            write("  Blender Object: " + (product_obj.name if product_obj else "None"))

        if inv.is_a("IfcRelDefinesByProperties"):
            pset = inv.RelatingPropertyDefinition

            write("  PROPERTY SET:")
            write("  " + str(pset))
            write("  Pset Name: " + str(getattr(pset, "Name", None)))

write("")
write("=" * 100)
write("Finished checking " + str(len(GUIDS)) + " GUID(s).")