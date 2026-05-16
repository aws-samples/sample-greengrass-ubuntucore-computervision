"""Shared test configuration and fixtures.

This conftest imports cv2 early (before any test module can mock it)
and stores the reference for use in tests that need real image processing.
"""

import cv2

# Store real cv2 reference before any test module can mock it
real_cv2 = cv2
