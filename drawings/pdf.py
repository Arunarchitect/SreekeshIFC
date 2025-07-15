from svglib.svglib import svg2rlg
from reportlab.graphics import renderSVG
from reportlab.graphics.shapes import Path, Rect, Circle, Ellipse, Polygon, PolyLine, Line

def set_opacity(obj, opacity):
    """Recursively set opacity for supported SVG elements"""
    if hasattr(obj, 'contents'):
        # If it's a group, process its contents
        for child in obj.contents:
            set_opacity(child, opacity)
    elif isinstance(obj, (Path, Rect, Circle, Ellipse, Polygon, PolyLine, Line)):
        # These shapes support fillOpacity and strokeOpacity
        if hasattr(obj, 'fillColor') and obj.fillColor is not None:
            obj.fillOpacity = opacity
        if hasattr(obj, 'strokeColor') and obj.strokeColor is not None:
            obj.strokeOpacity = opacity

def overlay_svgs(base_svg_path, overlay_svg_path, output_svg_path, opacity=0.2):
    """
    Overlay two SVG files with specified opacity for the overlay.
    
    Args:
        base_svg_path (str): Path to the base SVG file
        overlay_svg_path (str): Path to the overlay SVG file
        output_svg_path (str): Path to save the resulting SVG
        opacity (float): Opacity of the overlay (0.0 to 1.0)
    """
    # Load both SVG files
    base_drawing = svg2rlg(base_svg_path)
    overlay_drawing = svg2rlg(overlay_svg_path)
    
    if base_drawing is None:
        raise ValueError(f"Could not load base SVG file: {base_svg_path}")
    if overlay_drawing is None:
        raise ValueError(f"Could not load overlay SVG file: {overlay_svg_path}")
    
    # Set opacity for the overlay drawing
    set_opacity(overlay_drawing, opacity)
    
    # Combine the drawings - base first, then overlay
    base_drawing.add(overlay_drawing)
    
    # Save as SVG (opened in text mode now)
    renderSVG.drawToFile(base_drawing, output_svg_path)
    
    print(f"Successfully created overlay SVG at: {output_svg_path}")

# Example usage
if __name__ == "__main__":
    base_svg = "Plumbing_base.svg"  # Base SVG file
    overlay_svg = "Plumbing.svg"    # Overlay SVG file
    output_svg = "Test.svg"      # Output file
    
    overlay_svgs(base_svg, overlay_svg, output_svg, opacity=0.2)