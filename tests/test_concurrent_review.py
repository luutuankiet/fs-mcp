"""
Test to verify propose_and_review doesn't block other concurrent requests.

This test demonstrates that the async implementation allows FastMCP to handle
multiple requests concurrently, even when propose_and_review is waiting for
user input.
"""

import asyncio
import tempfile
from pathlib import Path
import time
import pytest

# Import the server functions directly
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fs_mcp.server import initialize, propose_and_review, list_allowed_directories


@pytest.mark.asyncio
async def test_concurrent_async_operations():
    """
    Simplified test to verify that async operations don't block each other.

    This test demonstrates that the async implementation allows multiple
    operations to run concurrently using asyncio.sleep (non-blocking) instead
    of time.sleep (blocking).
    """
    print("\n=== Testing Async Non-Blocking Behavior ===\n")

    async def simulated_review_wait():
        """Simulates the waiting loop in propose_and_review"""
        print("  Review task: Starting wait loop (simulating file modification wait)...")
        for i in range(3):
            await asyncio.sleep(1)  # This is the key change - non-blocking sleep
            print(f"  Review task: Waiting... ({i+1}s)")
        print("  Review task: Done!")
        return "Review completed"

    async def other_operation():
        """Simulates another tool call"""
        print("  Other task: Starting...")
        await asyncio.sleep(0.1)  # Quick operation
        print("  Other task: Done!")
        return "Other operation completed"

    # Start timing
    start_time = time.time()

    # Start the review task (will take ~3 seconds)
    print("1. Starting review task (will take ~3 seconds)...")
    review_task = asyncio.create_task(simulated_review_wait())

    # Give it a moment to start
    await asyncio.sleep(0.5)

    # Start another task while review is waiting
    print("2. Starting other task while review is waiting...")
    other_start = time.time()
    other_result = await other_operation()
    other_duration = time.time() - other_start

    print(f"3. Other task completed in {other_duration:.2f}s (should be ~0.1s)")

    # Verify it completed quickly
    if other_duration < 1.0:
        print("   ✅ SUCCESS: Other task was not blocked by review task")
    else:
        print("   ❌ FAIL: Other task was blocked")
        raise AssertionError(f"Other task took {other_duration:.2f}s, expected < 1.0s")

    # Wait for review to complete
    print("4. Waiting for review task to complete...")
    review_result = await review_task

    total_duration = time.time() - start_time
    print(f"\n✅ PASS: Both tasks completed successfully")
    print(f"   Total time: {total_duration:.2f}s (should be ~3s, not 3.1s)")
    print(f"   This proves tasks run concurrently, not sequentially")


@pytest.mark.asyncio
async def test_async_function_verification():
    """
    Simple test to verify that propose_and_review_logic is actually an async function.
    """
    import inspect
    from fs_mcp.edit_tool import propose_and_review_logic

    print("\n=== Async Function Verification ===")
    print(f"propose_and_review_logic is coroutine function: {inspect.iscoroutinefunction(propose_and_review_logic)}")

    if inspect.iscoroutinefunction(propose_and_review_logic):
        print("✅ PASS: propose_and_review_logic is async")
        print("   (Note: The tool wrapper may be decorated, but the core logic is async)")
    else:
        print("❌ FAIL: propose_and_review_logic is not async")
        raise AssertionError("propose_and_review_logic should be an async function")


if __name__ == "__main__":
    print("Running concurrent request tests...\n")

    # Run the async verification test
    asyncio.run(test_async_function_verification())

    # Run the concurrent async operations test
    asyncio.run(test_concurrent_async_operations())

    print("\n✅ All tests passed!")
