import cv2
import numpy as np

def detect_color(image_crop):
    """
    Detect the dominant color of a vehicle from its image crop.
    """
    if image_crop is None or image_crop.size == 0:
        return "Unknown"

    try:
        # Resize to small image for speed
        img = cv2.resize(image_crop, (50, 50))
        # Take the center ROI to avoid background as much as possible
        center_roi = img[15:35, 15:35]
        if center_roi.size > 0:
            img = center_roi

        pixels = img.reshape(-1, 3)
        pixels = np.float32(pixels)

        # K-means to find dominant colors
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        _, labels, centers = cv2.kmeans(pixels, 3, None, criteria, 5, cv2.KMEANS_RANDOM_CENTERS)

        # Get the most frequent color
        counts = np.bincount(labels.flatten())
        dominant_bgr = centers[np.argmax(counts)]
        
        return _bgr_to_name(dominant_bgr)
    except Exception:
        return "Unknown"

def _bgr_to_name(bgr):
    b, g, r = bgr
    # Simple heuristic-based mapping
    
    # 1. Grayscale check (White, Silver, Gray, Black)
    # If R, G, B are close to each other
    if max(r, g, b) - min(r, g, b) < 30:
        if max(r, g, b) > 200: return "White"
        if max(r, g, b) > 150: return "Silver"
        if max(r, g, b) > 70: return "Gray"
        return "Black"
        
    # 2. Chromatic colors
    if r > g and r > b:
        if g > 150 and r > 150: return "Yellow"
        return "Red"
    if g > r and g > b: return "Green"
    if b > r and b > g: return "Blue"
    
    return "Unknown"
