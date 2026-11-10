"""Ignore presentation tags when legacy tests compare visible clinical text.

Only the bold/color tags introduced or expanded in 6.54 are stripped. Other
markup, escaped clinical data, SVG dimensions and CSS remain testable. New
6.54 tests explicitly verify these tags, colors and normal-weight values.
"""
import re

def without_style_tags(markup):
    return re.sub(r'</?(?:b|font|tspan)(?:\s[^>]*)?>', '', markup)
