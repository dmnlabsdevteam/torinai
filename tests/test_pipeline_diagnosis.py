#!/usr/bin/env python3
"""
Diagnose the entire Vision→THE BRAIN→Memory pipeline
Test each component separately to find the bottleneck
"""
import pytest
import asyncio
import sys
import time
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))


@pytest.mark.asyncio
async def test_brain_loading():
    """Test if THE BRAIN (32B) loads and can generate"""
    print("=" * 80)
    print("TEST 1: THE BRAIN (32B) Loading & Inference")
    print("=" * 80)

    from core.services.unified_llm import get_llm_service

    llm = get_llm_service()

    print("\nInitializing LLM service...")
    start = time.time()
    await llm.initialize()
    load_time = time.time() - start

    print(f"✓ LLM initialized in {load_time:.2f}s")
    print(f"  Model loaded: {llm.model_loaded}")
    if hasattr(llm, 'model_path'):
        print(f"  Model path: {llm.model_path}")

    # Test text generation
    print("\nTesting text generation (simple query)...")
    start = time.time()

    result = await llm.generate(
        prompt="What is 2+2?",
        max_tokens=50,
        temperature=0.3
    )

    gen_time = time.time() - start

    print(f"✓ Generated in {gen_time:.2f}s")
    print(f"  Response: {result['content'][:100]}")
    print(f"  Tokens: {result.get('tokens_used', 'N/A')}")

    return llm


@pytest.mark.asyncio
# Helper, not a pytest test: it takes an argument and is driven by the
# script's own runner below. Named `test_*` it was collected anyway and
# pytest failed resolving the argument as a fixture -- an error that
# reported the file as broken while the script itself worked.
async def check_vision_only(llm):
    """Test vision model only (without THE BRAIN)"""
    print("\n" + "=" * 80)
    print("TEST 2: Vision Model Only (no THE BRAIN)")
    print("=" * 80)

    test_image = "/Users/stefan/Dominion Labs/TorinAI/test_data/vision_test.png"

    print(f"\nLoading vision model...")
    start = time.time()

    success = await llm._load_vision_model()

    load_time = time.time() - start
    print(f"✓ Vision model loaded in {load_time:.2f}s")
    print(f"  Success: {success}")
    print(f"  Model loaded: {llm.vision_model_loaded}")

    # Generate with vision (bypassing THE BRAIN for now)
    print(f"\nGenerating vision analysis (simple query)...")
    print(f"  Image: {test_image}")

    # We'll manually test just the vision part
    from qwen_vl_utils import process_vision_info

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": test_image},
                {"type": "text", "text": "What color is the circle?"}
            ]
        }
    ]

    # Prepare inputs
    text = llm.vision_processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)

    inputs = llm.vision_processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt"
    )

    # Move to device
    if llm.device.value == "mps":
        inputs = inputs.to("mps")

    start = time.time()
    generated_ids = llm.vision_model.generate(
        **inputs,
        max_new_tokens=50,
        temperature=0.7
    )
    gen_time = time.time() - start

    # Decode
    generated_ids_trimmed = [
        out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]

    vision_response = llm.vision_processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False
    )[0]

    tokens = len(generated_ids_trimmed[0])

    print(f"✓ Vision generated in {gen_time:.2f}s")
    print(f"  Response: {vision_response}")
    print(f"  Tokens: {tokens}")
    print(f"  Speed: {tokens/gen_time:.2f} tok/s")


@pytest.mark.asyncio
# Helper, not a pytest test: it takes an argument and is driven by the
# script's own runner below. Named `test_*` it was collected anyway and
# pytest failed resolving the argument as a fixture -- an error that
# reported the file as broken while the script itself worked.
async def check_brain_text_only(llm):
    """Test THE BRAIN with a text-only query (no vision)"""
    print("\n" + "=" * 80)
    print("TEST 3: THE BRAIN Text Generation (no vision)")
    print("=" * 80)

    print("\nGenerating with THE BRAIN (moderate complexity)...")
    start = time.time()

    result = await llm.generate(
        prompt="Explain why the sky is blue in one sentence.",
        max_tokens=100,
        temperature=0.7
    )

    gen_time = time.time() - start

    print(f"✓ Generated in {gen_time:.2f}s")
    print(f"  Response: {result['content'][:200]}")
    print(f"  Tokens: {result.get('tokens_used', 'N/A')}")

    if result.get('tokens_used'):
        print(f"  Speed: {result['tokens_used']/gen_time:.2f} tok/s")


async def main():
    print("\n" + "=" * 80)
    print("PIPELINE DIAGNOSIS")
    print("=" * 80)

    try:
        # Test 1: Can THE BRAIN load and generate?
        llm = await test_brain_loading()

        # Test 2: Can vision model work independently?
        await check_vision_only(llm)

        # Test 3: How fast is THE BRAIN for text?
        await check_brain_text_only(llm)

        print("\n" + "=" * 80)
        print("DIAGNOSIS COMPLETE")
        print("=" * 80)
        print("\nNext step: Test combined vision→THE BRAIN if all components work")

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
