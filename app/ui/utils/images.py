"""Image display utilities for Streamlit UI."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError
import streamlit as st
from bs4 import BeautifulSoup


# Thumbnail size for preview - larger size reduces blurriness when displayed
THUMBNAIL_MAX_SIZE = (600, 600)
THUMBNAIL_ASPECT_RATIO = True
# Quality setting for JPEG thumbnails (1-100, higher = better quality)
THUMBNAIL_QUALITY = 95


def create_thumbnail(image_path: Path, max_size: tuple[int, int] = THUMBNAIL_MAX_SIZE) -> Optional[Image.Image]:
    """Create a high-quality thumbnail from an image file.
    
    Uses LANCZOS resampling for best quality and preserves aspect ratio.
    """
    try:
        with image_path.open("rb") as fh:
            img = Image.open(fh)
            # Convert to RGB if necessary (for JPEG compatibility)
            if img.mode in ("RGBA", "LA", "P"):
                # Create white background for transparent images
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
            
            # Create thumbnail with high-quality resampling
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            return img
    except (UnidentifiedImageError, OSError, Exception):
        return None


def create_thumbnail_from_bytes(image_bytes: bytes, max_size: tuple[int, int] = THUMBNAIL_MAX_SIZE) -> Optional[Image.Image]:
    """Create a high-quality thumbnail from image bytes.
    
    Uses LANCZOS resampling for best quality and preserves aspect ratio.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert to RGB if necessary (for JPEG compatibility)
        if img.mode in ("RGBA", "LA", "P"):
            # Create white background for transparent images
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        
        # Create thumbnail with high-quality resampling
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        return img
    except (UnidentifiedImageError, OSError, Exception):
        return None


def display_image_with_dialog(
    image_path: Optional[Path] = None,
    image_bytes: Optional[bytes] = None,
    image_pil: Optional[Image.Image] = None,
    caption: str = "",
    key: Optional[str] = None,
) -> None:
    """Display an image as a thumbnail with click-to-expand dialog.
    
    Args:
        image_path: Path to image file
        image_bytes: Image bytes (alternative to image_path)
        image_pil: PIL Image object (alternative to image_path/image_bytes)
        caption: Caption for the image
        key: Unique key for Streamlit components
    """
    # Get the image
    full_image = None
    if image_pil is None:
        if image_path and image_path.exists():
            thumbnail = create_thumbnail(image_path)
            if thumbnail:
                try:
                    full_image = Image.open(image_path)
                except Exception:
                    full_image = None
        elif image_bytes:
            thumbnail = create_thumbnail_from_bytes(image_bytes)
            if thumbnail:
                try:
                    full_image = Image.open(io.BytesIO(image_bytes))
                except Exception:
                    full_image = None
        else:
            st.warning(f"Image not available: {caption}")
            return
    else:
        thumbnail = image_pil.copy()
        thumbnail.thumbnail(THUMBNAIL_MAX_SIZE, Image.Resampling.LANCZOS)
        full_image = image_pil
    
    if thumbnail is None:
        st.warning(f"Could not create thumbnail: {caption}")
        return
    
    # Display thumbnail with proper sizing
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        # Convert thumbnail to bytes for display with high quality
        buffer = io.BytesIO()
        # Use JPEG for better quality/size ratio, PNG for transparency
        if thumbnail.mode == "RGB":
            thumbnail.save(buffer, format="JPEG", quality=THUMBNAIL_QUALITY, optimize=True)
        else:
            thumbnail.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)
        
        # Show thumbnail with max width constraint to prevent huge display
        # use_container_width=False and specify width to control size
        st.image(buffer, caption=caption, use_container_width=False, width=min(thumbnail.width, 600))
        
        # Use a button to trigger the full-size view
        dialog_key = f"image_dialog_{key or caption}"
        if st.button("🖼️ View Full Size", key=f"btn_{dialog_key}", use_container_width=True):
            st.session_state[dialog_key] = not st.session_state.get(dialog_key, False)
        
        # Display full-size image in expander if button was clicked
        if st.session_state.get(dialog_key, False):
            with st.expander("Full Size Image", expanded=True):
                st.markdown(f"### {caption}")
                if image_path and image_path.exists():
                    st.image(str(image_path), caption=caption, use_container_width=True)
                elif image_bytes:
                    st.image(image_bytes, caption=caption, use_container_width=True)
                elif full_image:
                    buffer_full = io.BytesIO()
                    # Try to preserve original format
                    try:
                        format_map = {
                            "PNG": "PNG",
                            "JPEG": "JPEG",
                            "GIF": "GIF",
                            "WEBP": "WEBP",
                        }
                        img_format = full_image.format or "PNG"
                        if img_format == "JPEG" and full_image.mode == "RGB":
                            full_image.save(buffer_full, format=img_format, quality=95)
                        else:
                            full_image.save(buffer_full, format=img_format)
                    except Exception:
                        full_image.save(buffer_full, format="PNG")
                    buffer_full.seek(0)
                    st.image(buffer_full, caption=caption, use_container_width=True)
                
                if st.button("Close", key=f"close_{dialog_key}"):
                    st.session_state[dialog_key] = False
                    st.rerun()


def process_html_images(html_content: str, max_thumbnail_size: tuple[int, int] = THUMBNAIL_MAX_SIZE) -> str:
    """Process HTML content to convert images to thumbnails with click-to-expand.
    
    Handles both regular <img> tags and base64-encoded images.
    """
    if not html_content:
        return html_content
    
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        images = soup.find_all("img")
        
        for img in images:
            src = img.get("src", "")
            original_src = src
            
            # Handle base64 images
            if src.startswith("data:image"):
                # Extract base64 data
                try:
                    # Format: data:image/png;base64,<data>
                    header, data = src.split(",", 1)
                    mime_type = header.split(";")[0].split(":")[1]  # e.g., "image/png"
                    
                    # Decode base64
                    image_bytes = base64.b64decode(data)
                    
                    # Create thumbnail
                    thumbnail = create_thumbnail_from_bytes(image_bytes, max_thumbnail_size)
                    if thumbnail:
                        # Convert thumbnail to base64 with high quality
                        buffer = io.BytesIO()
                        # Determine format from mime type
                        format_map = {
                            "image/png": "PNG",
                            "image/jpeg": "JPEG",
                            "image/jpg": "JPEG",
                            "image/gif": "GIF",
                            "image/webp": "WEBP",
                        }
                        img_format = format_map.get(mime_type, "JPEG")
                        # Use high quality for JPEG
                        if img_format == "JPEG" and thumbnail.mode == "RGB":
                            thumbnail.save(buffer, format=img_format, quality=THUMBNAIL_QUALITY, optimize=True)
                        else:
                            thumbnail.save(buffer, format=img_format, optimize=True)
                        buffer.seek(0)
                        thumbnail_data = base64.b64encode(buffer.read()).decode("utf-8")
                        
                        # Update img tag with thumbnail and add click handler
                        # Use larger max size for better quality display
                        img["src"] = f"data:{mime_type};base64,{thumbnail_data}"
                        img["style"] = "cursor: pointer; max-width: 600px; max-height: 600px; object-fit: contain; image-rendering: -webkit-optimize-contrast; image-rendering: crisp-edges;"
                        img["onclick"] = f"showFullImage('{original_src}')"
                        img["title"] = "Click to view full size"
                except Exception:
                    # If processing fails, just add styling
                    img["style"] = "max-width: 600px; max-height: 600px; object-fit: contain; cursor: pointer; image-rendering: -webkit-optimize-contrast; image-rendering: crisp-edges;"
                    img["onclick"] = f"showFullImage('{original_src}')"
            else:
                # Regular image URL - just add styling and click handler
                img["style"] = "max-width: 600px; max-height: 600px; object-fit: contain; cursor: pointer; image-rendering: -webkit-optimize-contrast; image-rendering: crisp-edges;"
                img["onclick"] = f"showFullImage('{original_src}')"
                img["title"] = "Click to view full size"
        
        # Add JavaScript for full-size image display
        script = """
        <script>
        function showFullImage(src) {
            // Create modal overlay
            const overlay = document.createElement('div');
            overlay.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 10000; display: flex; align-items: center; justify-content: center; cursor: pointer;';
            
            // Create image container
            const imgContainer = document.createElement('div');
            imgContainer.style.cssText = 'max-width: 90%; max-height: 90%; position: relative;';
            
            // Create full-size image
            const fullImg = document.createElement('img');
            fullImg.src = src;
            fullImg.style.cssText = 'max-width: 100%; max-height: 100%; object-fit: contain;';
            
            // Create close button
            const closeBtn = document.createElement('button');
            closeBtn.innerHTML = '×';
            closeBtn.style.cssText = 'position: absolute; top: -40px; right: 0; background: white; border: none; border-radius: 50%; width: 40px; height: 40px; font-size: 30px; cursor: pointer; color: #333;';
            
            // Close on click
            overlay.onclick = function(e) {
                if (e.target === overlay || e.target === closeBtn) {
                    document.body.removeChild(overlay);
                }
            };
            
            imgContainer.appendChild(fullImg);
            imgContainer.appendChild(closeBtn);
            overlay.appendChild(imgContainer);
            document.body.appendChild(overlay);
        }
        </script>
        """
        
        # Insert script at the beginning of the body or html
        if soup.body:
            soup.body.insert(0, BeautifulSoup(script, "html.parser"))
        elif soup.html:
            soup.html.insert(0, BeautifulSoup(script, "html.parser"))
        else:
            soup.insert(0, BeautifulSoup(script, "html.parser"))
        
        return str(soup)
    except Exception:
        # If processing fails, return original HTML
        return html_content

