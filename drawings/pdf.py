from lxml import etree
import re
import cssutils

def merge_bonsai_svgs():
    # File paths
    base_svg = "Plumbing_base.svg"
    overlay_svg = "Plumbing.svg"
    output_svg = "Plumbing.svg"
    
    # Parse both SVGs with style preservation
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=False)
    
    # Read files as strings to preserve CSS
    with open(base_svg, 'r', encoding='utf-8') as f:
        base_content = f.read()
    with open(overlay_svg, 'r', encoding='utf-8') as f:
        overlay_content = f.read()
    
    # Parse the content
    base_tree = etree.fromstring(base_content.encode('utf-8'), parser)
    overlay_tree = etree.fromstring(overlay_content.encode('utf-8'), parser)
    
    # Extract CSS styles from both files
    base_css = extract_css(base_content)
    overlay_css = extract_css(overlay_content)
    
    # Combine CSS rules, giving priority to overlay styles
    combined_css = combine_css(base_css, overlay_css)
    
    # Create new style element with combined CSS
    style_element = etree.Element("style")
    style_element.text = etree.CDATA("\n" + combined_css + "\n")
    
    # Create a group for the overlay content
    overlay_group = etree.Element("g", id="plumbing_overlay")
    
    # Copy all elements from overlay to the group
    for element in overlay_tree:
        if element.tag.endswith("style"):
            continue  # Skip original style elements
        overlay_group.append(element)
    
    # Remove any existing style elements from base
    for elem in base_tree.xpath("//*[local-name()='style']"):
        elem.getparent().remove(elem)
    
    # Add combined style and overlay group to base SVG
    base_tree.insert(0, style_element)  # Add style at beginning
    base_root = base_tree
    base_root.append(overlay_group)
    
    # Write the output with proper XML declaration
    with open(output_svg, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n')
        f.write(etree.tostring(base_root, 
                             pretty_print=True, 
                             encoding='utf-8',
                             xml_declaration=False))
    
    print(f"Successfully merged Bonsai SVGs with styles preserved. Output saved to {output_svg}")

def extract_css(svg_content):
    """Extract CSS content from SVG"""
    css_matches = re.findall(r'<style.*?>(.*?)</style>', svg_content, re.DOTALL)
    return "\n".join([css.strip() for css in css_matches if css.strip()])

def combine_css(base_css, overlay_css):
    """Combine CSS rules with overlay taking precedence"""
    css_parser = cssutils.CSSParser()
    
    # Parse both CSS strings
    base_sheet = css_parser.parseString(base_css)
    overlay_sheet = css_parser.parseString(overlay_css)
    
    # Create new combined sheet
    combined_sheet = cssutils.css.CSSStyleSheet()
    
    # Add all rules from base first
    for rule in base_sheet:
        combined_sheet.add(rule)
    
    # Add overlay rules, which will override base rules
    for rule in overlay_sheet:
        # Remove any existing rules with same selector
        for existing in combined_sheet:
            if existing.selectorText == rule.selectorText:
                combined_sheet.remove(existing)
                break
        combined_sheet.add(rule)
    
    return combined_sheet.cssText.decode('utf-8')

if __name__ == "__main__":
    # Install cssutils if not available: pip install cssutils
    merge_bonsai_svgs()