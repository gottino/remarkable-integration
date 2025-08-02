"""
reMarkable to SVG converter module.

Refactored from rm2svg.py to integrate with the remarkable-integration project.
Handles conversion of .rm files (versions 3 and 5) to SVG format.
"""

import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Default reMarkable dimensions
DEFAULT_WIDTH = 1404
DEFAULT_HEIGHT = 1872

# Color mappings
STROKE_COLORS = {
    0: [0, 0, 0],       # Black
    1: [125, 125, 125], # Gray
    2: [255, 255, 255], # White
    3: [251, 247, 25],  # Yellow (highlighter)
}

# Colored annotations mapping
COLORED_STROKE_COLORS = {
    0: [0, 0, 0],       # Black
    1: [255, 0, 0],     # Red
    2: [255, 255, 255], # White
    3: [150, 0, 0],     # Dark red
    4: [0, 0, 125]      # Dark blue
}


@dataclass
class Segment:
    """Represents a segment within a stroke."""
    id: int
    xpos: float
    ypos: float
    speed: float
    tilt: float
    width: float
    pressure: float


@dataclass
class Stroke:
    """Represents a stroke containing multiple segments."""
    id: int
    pen: 'Pen'
    color: str
    width: float
    opacity: float
    segments: List[Segment]

    def __post_init__(self):
        if self.segments is None:
            self.segments = []

    def add_segment(self, segment: Segment):
        """Add a segment to this stroke."""
        self.segments.append(segment)


@dataclass
class Layer:
    """Represents a layer containing multiple strokes."""
    id: int
    strokes: List[Stroke]

    def __post_init__(self):
        if self.strokes is None:
            self.strokes = []

    def add_stroke(self, stroke: Stroke):
        """Add a stroke to this layer."""
        self.strokes.append(stroke)


@dataclass
class RmPage:
    """Represents a complete page with multiple layers."""
    layers: List[Layer]

    def __post_init__(self):
        if self.layers is None:
            self.layers = []

    def add_layer(self, layer: Layer):
        """Add a layer to this page."""
        self.layers.append(layer)


@dataclass
class ConversionResult:
    """Result of converting an .rm file."""
    success: bool
    svg_content: str = ""
    error_message: str = ""
    width: float = DEFAULT_WIDTH
    height: float = DEFAULT_HEIGHT


class RmToSvgConverter:
    """Main converter class for .rm files to SVG."""

    def __init__(self, coloured_annotations: bool = False):
        """
        Initialize the converter.
        
        Args:
            coloured_annotations: Use colored annotations for markup
        """
        self.coloured_annotations = coloured_annotations
        self.stroke_colors = COLORED_STROKE_COLORS if coloured_annotations else STROKE_COLORS

    def convert_file(self, input_path: str, output_path: str, 
                    width: float = DEFAULT_WIDTH, 
                    height: float = DEFAULT_HEIGHT) -> ConversionResult:
        """
        Convert an .rm file to SVG format.
        
        Args:
            input_path: Path to the .rm file
            output_path: Path for the output SVG file
            width: Desired width of the output
            height: Desired height of the output
            
        Returns:
            ConversionResult with success status and details
        """
        try:
            # Parse the .rm file
            page = self._parse_rm_file(input_path)
            if page is None:
                return ConversionResult(
                    success=False,
                    error_message="Failed to parse .rm file"
                )

            # Convert to SVG
            svg_content = self._convert_to_svg(page, width, height)
            
            # Write to file if output_path is provided
            if output_path:
                with open(output_path, 'w') as f:
                    f.write(svg_content)

            return ConversionResult(
                success=True,
                svg_content=svg_content,
                width=width,
                height=height
            )

        except Exception as e:
            logger.error(f"Error converting {input_path}: {e}")
            return ConversionResult(
                success=False,
                error_message=str(e)
            )

    def convert_to_string(self, input_path: str, 
                         width: float = DEFAULT_WIDTH, 
                         height: float = DEFAULT_HEIGHT) -> ConversionResult:
        """
        Convert an .rm file to SVG string without writing to file.
        
        Args:
            input_path: Path to the .rm file
            width: Desired width of the output
            height: Desired height of the output
            
        Returns:
            ConversionResult with SVG content as string
        """
        return self.convert_file(input_path, None, width, height)

    def _parse_rm_file(self, input_path: str) -> Optional[RmPage]:
        """Parse a .rm file and return a RmPage object."""
        try:
            with open(input_path, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            logger.error(f"File not found: {input_path}")
            return None

        if len(data) < 47:  # Minimum file size check
            logger.error("File too short to be a valid .rm file")
            return None

        offset = 0

        # Check file format version
        expected_header_v3 = b'reMarkable .lines file, version=3          '
        expected_header_v5 = b'reMarkable .lines file, version=5          '
        
        fmt = f'<{len(expected_header_v5)}sI'
        header, nlayers = struct.unpack_from(fmt, data, offset)
        offset += struct.calcsize(fmt)

        is_v3 = (header == expected_header_v3)
        is_v5 = (header == expected_header_v5)

        if not (is_v3 or is_v5) or nlayers < 1:
            logger.error(f"Invalid .rm file format. Header: {header}, Layers: {nlayers}")
            return None

        page = RmPage(layers=[])

        # Parse layers
        for layer_id in range(nlayers):
            layer = self._parse_layer(data, offset, layer_id, is_v5)
            if layer is None:
                return None
            page.add_layer(layer)
            offset = layer.offset_after_parsing  # Update offset

        return page

    def _parse_layer(self, data: bytes, offset: int, layer_id: int, is_v5: bool) -> Optional[Layer]:
        """Parse a single layer from the data."""
        try:
            fmt = '<I'
            (nstrokes,) = struct.unpack_from(fmt, data, offset)
            offset += struct.calcsize(fmt)

            layer = Layer(id=layer_id, strokes=[])

            for stroke_id in range(nstrokes):
                stroke, new_offset = self._parse_stroke(data, offset, stroke_id, is_v5)
                if stroke is None:
                    return None
                layer.add_stroke(stroke)
                offset = new_offset

            layer.offset_after_parsing = offset  # Store for caller
            return layer

        except Exception as e:
            logger.error(f"Error parsing layer {layer_id}: {e}")
            return None

    def _parse_stroke(self, data: bytes, offset: int, stroke_id: int, is_v5: bool) -> Tuple[Optional[Stroke], int]:
        """Parse a single stroke from the data."""
        try:
            if is_v5:
                fmt = '<IIIffI'
                pen_nr, colour, i_unk, width, unknown, nsegments = struct.unpack_from(fmt, data, offset)
            else:  # v3
                fmt = '<IIIfI'
                pen_nr, colour, i_unk, width, nsegments = struct.unpack_from(fmt, data, offset)
                unknown = 0

            offset += struct.calcsize(fmt)

            # Create pen object
            pen = self._create_pen(pen_nr, width, colour)
            
            # Determine color and opacity
            color_rgb = self.stroke_colors.get(colour, [0, 0, 0])
            color_str = f"rgb({color_rgb[0]},{color_rgb[1]},{color_rgb[2]})"
            opacity = pen.base_opacity

            stroke = Stroke(
                id=stroke_id,
                pen=pen,
                color=color_str,
                width=pen.base_width,
                opacity=opacity,
                segments=[]
            )

            # Parse segments
            for segment_id in range(nsegments):
                fmt = '<ffffff'
                xpos, ypos, speed, tilt, width_seg, pressure = struct.unpack_from(fmt, data, offset)
                offset += struct.calcsize(fmt)

                segment = Segment(
                    id=segment_id,
                    xpos=xpos,
                    ypos=ypos,
                    speed=speed,
                    tilt=tilt,
                    width=width_seg,
                    pressure=pressure
                )
                stroke.add_segment(segment)

            return stroke, offset

        except Exception as e:
            logger.error(f"Error parsing stroke {stroke_id}: {e}")
            return None, offset

    def _create_pen(self, pen_nr: int, width: float, colour: int) -> 'Pen':
        """Create appropriate pen object based on pen number."""
        # Adjust for colored annotations
        if self.coloured_annotations:
            if pen_nr in [2, 15]:  # Ballpoint
                colour = 4
            elif pen_nr in [5, 18]:  # Highlighter
                colour = 3

        pen_classes = {
            (0, 12): Brush,
            (21,): Caligraphy,
            (3, 16): Marker,
            (2, 15): Ballpoint,
            (4, 17): Fineliner,
            (1, 14): Pencil,
            (7, 13): MechanicalPencil,
            (5, 18): Highlighter,
            (8,): EraseArea,
            (6,): Eraser,
        }

        for pen_numbers, pen_class in pen_classes.items():
            if pen_nr in pen_numbers:
                return pen_class(width, colour)

        logger.warning(f"Unknown pen number: {pen_nr}, using default pen")
        return Pen(width, colour)

    def _convert_to_svg(self, page: RmPage, width: float, height: float) -> str:
        """Convert a RmPage to SVG string."""
        svg_lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" height="{height}" width="{width}">',
            self._get_svg_header(),
            '    <g id="p1" style="display:inline">',
            '        <filter id="blurMe"><feGaussianBlur in="SourceGraphic" stdDeviation="10" /></filter>'
        ]

        # Process each layer
        for layer in page.layers:
            svg_lines.append(f'        <!-- layer: {layer.id} -->')
            
            for stroke in layer.strokes:
                stroke_svg = self._convert_stroke_to_svg(stroke, width, height)
                svg_lines.extend(stroke_svg)

        # Close SVG
        svg_lines.extend([
            f'        <rect x="0" y="0" width="{width}" height="{height}" fill-opacity="0"/>',
            '    </g>',
            '</svg>'
        ])

        return '\n'.join(svg_lines)

    def _get_svg_header(self) -> str:
        """Get SVG header with embedded script."""
        return '''    <script type="application/ecmascript"> <![CDATA[
        var visiblePage = 'p1';
        function goToPage(page) {
            document.getElementById(visiblePage).setAttribute('style', 'display: none');
            document.getElementById(page).setAttribute('style', 'display: inline');
            visiblePage = page;
        }
    ]]>
    </script>'''

    def _convert_stroke_to_svg(self, stroke: Stroke, svg_width: float, svg_height: float) -> List[str]:
        """Convert a single stroke to SVG polylines."""
        lines = [f'        <!-- stroke: {stroke.id} pen: "{stroke.pen.name}" -->']
        
        if not stroke.segments:
            return lines

        # Calculate scaling ratio
        ratio = (svg_height / svg_width) / (DEFAULT_HEIGHT / DEFAULT_WIDTH)
        
        # Start first polyline
        current_polyline = [
            '        <polyline ',
            f'style="fill:none;stroke:{stroke.color};stroke-width:{stroke.width};opacity:{stroke.opacity}" ',
            f'stroke-linecap="{stroke.pen.stroke_cap}" ',
            'points="'
        ]

        last_x, last_y = -1, -1
        last_width = 0

        for segment in stroke.segments:
            # Scale coordinates
            if ratio > 1:
                x = ratio * ((segment.xpos * svg_width) / DEFAULT_WIDTH)
                y = (segment.ypos * svg_height) / DEFAULT_HEIGHT
            else:
                x = (segment.xpos * svg_width) / DEFAULT_WIDTH
                y = (1 / ratio) * (segment.ypos * svg_height) / DEFAULT_HEIGHT

            # Check if we need to start a new polyline segment
            if segment.id % stroke.pen.segment_length == 0:
                # Get dynamic properties from pen
                segment_color = stroke.pen.get_segment_color(
                    segment.speed, segment.tilt, segment.width, segment.pressure, last_width
                )
                segment_width = stroke.pen.get_segment_width(
                    segment.speed, segment.tilt, segment.width, segment.pressure, last_width
                )
                segment_opacity = stroke.pen.get_segment_opacity(
                    segment.speed, segment.tilt, segment.width, segment.pressure, last_width
                )

                # Close current polyline and start new one
                current_polyline.append('"/>')
                lines.append(''.join(current_polyline))

                current_polyline = [
                    '        <polyline ',
                    f'style="fill:none; stroke:{segment_color} ;stroke-width:{segment_width:.3f};opacity:{segment_opacity}" ',
                    f'stroke-linecap="{stroke.pen.stroke_cap}" ',
                    'points="'
                ]

                # Connect to previous segment if needed
                if last_x != -1:
                    current_polyline.append(f'{last_x:.3f},{last_y:.3f} ')

                last_width = segment_width

            # Add point to current polyline
            current_polyline.append(f'{x:.3f},{y:.3f} ')
            last_x, last_y = x, y

        # Close final polyline
        current_polyline.append('" />')
        lines.append(''.join(current_polyline))

        return lines


# Pen classes
class Pen:
    """Base pen class."""
    
    def __init__(self, base_width: float, base_color: int):
        self.base_width = base_width
        self.base_color = STROKE_COLORS.get(base_color, [0, 0, 0])
        self.segment_length = 1000
        self.stroke_cap = "round"
        self.base_opacity = 1
        self.name = "Basic Pen"

    def get_segment_width(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> float:
        return self.base_width

    def get_segment_color(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> str:
        return f"rgb({self.base_color[0]},{self.base_color[1]},{self.base_color[2]})"

    def get_segment_opacity(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> float:
        return self.base_opacity

    @staticmethod
    def cutoff(value: float) -> float:
        """Ensure value is between 0 and 1."""
        return max(0, min(1, value))


class Fineliner(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.base_width = (base_width ** 2.1) * 1.3
        self.name = "Fineliner"


class Ballpoint(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.segment_length = 5
        self.name = "Ballpoint"

    def get_segment_width(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> float:
        return (0.5 + pressure) + (1 * width) - 0.5 * (speed / 50)

    def get_segment_color(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> str:
        intensity = (0.1 * -(speed / 35)) + (1.2 * pressure) + 0.5
        intensity = self.cutoff(intensity)
        color_val = int(abs(intensity - 1) * 255)
        return f"rgb({color_val},{color_val},{color_val})"


class Marker(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.segment_length = 3
        self.name = "Marker"

    def get_segment_width(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> float:
        return 0.9 * (((1 * width)) - 0.4 * tilt) + (0.1 * last_width)


class Pencil(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.segment_length = 2
        self.name = "Pencil"

    def get_segment_width(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> float:
        segment_width = 0.7 * ((((0.8 * self.base_width) + (0.5 * pressure)) * (1 * width)) - (0.25 * tilt**1.8) - (0.6 * speed / 50))
        max_width = self.base_width * 10
        return min(segment_width, max_width)

    def get_segment_opacity(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> float:
        segment_opacity = (0.1 * -(speed / 35)) + (1 * pressure)
        return self.cutoff(segment_opacity) - 0.1


class MechanicalPencil(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.base_width = self.base_width ** 2
        self.base_opacity = 0.7
        self.name = "Mechanical Pencil"


class Brush(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.segment_length = 2
        self.stroke_cap = "round"
        self.name = "Brush"

    def get_segment_width(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> float:
        return 0.7 * (((1 + (1.4 * pressure)) * (1 * width)) - (0.5 * tilt) - (0.5 * speed / 50))

    def get_segment_color(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> str:
        intensity = (pressure ** 1.5 - 0.2 * (speed / 50)) * 1.5
        intensity = self.cutoff(intensity)
        rev_intensity = abs(intensity - 1)
        
        r = int(rev_intensity * (255 - self.base_color[0]))
        g = int(rev_intensity * (255 - self.base_color[1]))
        b = int(rev_intensity * (255 - self.base_color[2]))
        
        return f"rgb({r},{g},{b})"


class Highlighter(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.stroke_cap = "square"
        self.base_opacity = 0.3
        self.base_width = 15
        self.name = "Highlighter"


class Eraser(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.stroke_cap = "square"
        self.base_width = self.base_width * 2
        self.name = "Eraser"


class EraseArea(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.stroke_cap = "square"
        self.base_opacity = 0
        self.name = "Erase Area"


class Caligraphy(Pen):
    def __init__(self, base_width: float, base_color: int):
        super().__init__(base_width, base_color)
        self.segment_length = 2
        self.name = "Calligraphy"

    def get_segment_width(self, speed: float, tilt: float, width: float, pressure: float, last_width: float) -> float:
        return 0.9 * (((1 + pressure) * (1 * width)) - 0.3 * tilt) + (0.1 * last_width)


# Convenience function for backward compatibility
def rm2svg(input_file: str, output_file: str, coloured_annotations: bool = False,
           width: float = DEFAULT_WIDTH, height: float = DEFAULT_HEIGHT) -> ConversionResult:
    """
    Convert .rm file to SVG format.
    
    Args:
        input_file: Path to input .rm file
        output_file: Path to output SVG file
        coloured_annotations: Use colored annotations
        width: Output width
        height: Output height
        
    Returns:
        ConversionResult object
    """
    converter = RmToSvgConverter(coloured_annotations)
    return converter.convert_file(input_file, output_file, width, height)
