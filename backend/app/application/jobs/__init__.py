"""Job queue abstraction layer — design-only in Phase 6.

This package defines contracts for durable job execution. No queue backend
dependency is imported or required at runtime. The application continues to
execute generation tasks in-process via asyncio.create_task.

Phase 6A+ will introduce actual queue backends behind these interfaces.
"""
