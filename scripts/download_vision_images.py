#!/usr/bin/env python3
"""
Download actual images for Vision-FLAN training
"""

import json
import requests
from pathlib import Path
from PIL import Image
from io import BytesIO
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_images_for_dataset(jsonl_path, output_dir, max_images=1000):
    """Download images from COCO dataset"""
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load dataset
    samples = []
    with open(jsonl_path, 'r') as f:
        for line in f:
            samples.append(json.loads(line))
    
    logger.info(f"Found {len(samples)} samples")
    
    # COCO dataset base URLs
    coco_urls = [
        "http://images.cocodataset.org/train2017/",
        "http://images.cocodataset.org/val2017/",
    ]
    
    downloaded = 0
    failed = 0
    skipped = 0
    
    for i, sample in enumerate(samples[:max_images]):
        image_filename = sample.get('image', '')
        if not image_filename:
            failed += 1
            continue
        
        output_path = output_dir / image_filename
        
        # Skip if already exists
        if output_path.exists():
            skipped += 1
            continue
        
        # Try both train and val datasets
        success = False
        for base_url in coco_urls:
            try:
                image_url = base_url + image_filename
                response = requests.get(image_url, timeout=15)
                
                if response.status_code == 200:
                    # Save image
                    image = Image.open(BytesIO(response.content))
                    image = image.convert('RGB')
                    image.save(output_path, 'JPEG')
                    downloaded += 1
                    success = True
                    
                    if downloaded % 50 == 0:
                        logger.info(f"Progress: {downloaded} downloaded, {failed} failed, {skipped} skipped")
                    break
                    
            except Exception as e:
                continue
        
        if not success:
            logger.warning(f"Could not download: {image_filename}")
            failed += 1
    
    logger.info(f"\n✓ Complete! Downloaded: {downloaded}, Failed: {failed}, Skipped: {skipped}")
    return downloaded


if __name__ == "__main__":
    logger.info("Downloading images for Vision-FLAN training...")
    
    count = download_images_for_dataset(
        jsonl_path="data/vision_flan/llava_instruct_1000.jsonl",
        output_dir="data/vision_flan/images",
        max_images=1000
    )
    
    logger.info(f"Images saved to: data/vision_flan/images/")
