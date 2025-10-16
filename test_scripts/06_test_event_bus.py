#!/usr/bin/env python3
"""
Test: Event Bus
Purpose: Test event publishing and subscription

Tests:
- Event publishing and receiving
- Multiple subscribers
- Event handler failures don't block others
- Event bus lifecycle
"""

import asyncio
import sys

from fixtures import (
    print_test_header, print_pass, print_fail, print_summary, print_info,
    EventCollector, assert_equal, assert_true
)

from app.core.event_bus import EventBus
from app.models.schemas import EventType


async def test_event_publishing_and_receiving():
    """Test basic event publishing and receiving"""
    bus = EventBus()
    collector = EventCollector()

    # Subscribe to event
    bus.subscribe(EventType.WORKFLOW_STARTED, collector.handler)

    # Start bus
    await bus.start()

    try:
        # Publish event
        await bus.publish(EventType.WORKFLOW_STARTED, {"workflow_id": "test-123"})

        # Wait for processing
        await asyncio.sleep(0.2)

        # Verify event received
        events = collector.get_events()
        assert_equal(len(events), 1, "Should receive one event")
        assert_equal(events[0]["workflow_id"], "test-123")

    finally:
        await bus.stop()


async def test_multiple_subscribers():
    """Test multiple subscribers to same event"""
    bus = EventBus()
    collector1 = EventCollector()
    collector2 = EventCollector()
    collector3 = EventCollector()

    # Subscribe all three
    bus.subscribe(EventType.WORKFLOW_COMPLETED, collector1.handler)
    bus.subscribe(EventType.WORKFLOW_COMPLETED, collector2.handler)
    bus.subscribe(EventType.WORKFLOW_COMPLETED, collector3.handler)

    await bus.start()

    try:
        # Publish event
        await bus.publish(EventType.WORKFLOW_COMPLETED, {"result": "success"})
        await asyncio.sleep(0.2)

        # All should receive
        assert_equal(collector1.count(), 1, "Collector 1 should receive event")
        assert_equal(collector2.count(), 1, "Collector 2 should receive event")
        assert_equal(collector3.count(), 1, "Collector 3 should receive event")

    finally:
        await bus.stop()


async def test_handler_failure_doesnt_block_others():
    """Test that one handler failure doesn't block other handlers"""
    bus = EventBus()
    success_collector = EventCollector()

    async def failing_handler(data: dict):
        raise Exception("Intentional failure")

    # Subscribe both handlers
    bus.subscribe(EventType.APPROVAL_RECEIVED, failing_handler)
    bus.subscribe(EventType.APPROVAL_RECEIVED, success_collector.handler)

    await bus.start()

    try:
        # Publish event
        await bus.publish(EventType.APPROVAL_RECEIVED, {"approval_id": "test"})
        await asyncio.sleep(0.2)

        # Success handler should still receive event
        assert_equal(
            success_collector.count(),
            1,
            "Success handler should receive event despite other handler failing"
        )

    finally:
        await bus.stop()


async def test_event_bus_lifecycle():
    """Test event bus start/stop lifecycle"""
    bus = EventBus()

    # Initially not running
    stats = bus.get_stats()
    assert_equal(stats["running"], False, "Should not be running initially")

    # Start
    await bus.start()
    stats = bus.get_stats()
    assert_equal(stats["running"], True, "Should be running after start")

    # Stop
    await bus.stop()
    stats = bus.get_stats()
    assert_equal(stats["running"], False, "Should not be running after stop")


async def test_multiple_event_types():
    """Test subscribing to different event types"""
    bus = EventBus()
    workflow_collector = EventCollector()
    approval_collector = EventCollector()

    bus.subscribe(EventType.WORKFLOW_STARTED, workflow_collector.handler)
    bus.subscribe(EventType.APPROVAL_REQUESTED, approval_collector.handler)

    await bus.start()

    try:
        # Publish different event types
        await bus.publish(EventType.WORKFLOW_STARTED, {"id": "w1"})
        await bus.publish(EventType.APPROVAL_REQUESTED, {"id": "a1"})
        await bus.publish(EventType.WORKFLOW_STARTED, {"id": "w2"})

        await asyncio.sleep(0.2)

        # Verify correct routing
        assert_equal(workflow_collector.count(), 2, "Should receive 2 workflow events")
        assert_equal(approval_collector.count(), 1, "Should receive 1 approval event")

    finally:
        await bus.stop()


async def test_event_queue_stats():
    """Test event bus statistics"""
    bus = EventBus(max_queue_size=100)
    collector = EventCollector()

    bus.subscribe(EventType.WORKFLOW_STARTED, collector.handler)
    bus.subscribe(EventType.WORKFLOW_COMPLETED, collector.handler)

    stats = bus.get_stats()
    assert_equal(stats["max_queue_size"], 100, "Max queue size should be 100")
    assert_true(len(stats["event_types"]) > 0, "Should have event types registered")


async def main():
    """Run all event bus tests"""
    print_test_header("Event Bus Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("Event publishing and receiving", test_event_publishing_and_receiving),
        ("Multiple subscribers", test_multiple_subscribers),
        ("Handler failure doesn't block others", test_handler_failure_doesnt_block_others),
        ("Event bus lifecycle", test_event_bus_lifecycle),
        ("Multiple event types", test_multiple_event_types),
        ("Event queue statistics", test_event_queue_stats),
    ]

    for test_name, test_func in tests:
        try:
            await test_func()
            print_pass(test_name)
            tests_passed += 1
        except Exception as e:
            print_fail(test_name, str(e))
            import traceback
            traceback.print_exc()
            tests_failed += 1

    print_summary(tests_passed, tests_failed)
    return 0 if tests_failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
