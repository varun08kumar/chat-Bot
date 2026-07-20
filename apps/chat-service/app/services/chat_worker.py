"""Background consumer that turns queued chat jobs into LLM calls.

Runs inside every chat-service replica (not a separate deployment/image),
so the job queue's crash-survival property comes for free from the
existing multi-replica setup (see infra/k8s/21-chat-service.yaml's
HorizontalPodAutoscaler): if the replica that enqueued a job dies before
finishing it, another replica's worker loop reclaims and finishes it.
"""

from __future__ import annotations

import asyncio
import time

from llm_obs_shared.logging import get_logger

from app.config import Settings
from app.services.chat_service import ChatService, PreparedChat
from app.services.job_queue import ChatJobQueue, JobEntry

logger = get_logger(__name__)


async def run_worker(
    *,
    chat_service: ChatService,
    job_queue: ChatJobQueue,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    await job_queue.ensure_group()
    last_reclaim = 0.0
    logger.info("Chat job worker started")
    while not stop.is_set():
        try:
            now = time.monotonic()
            if now - last_reclaim >= settings.chat_job_claim_interval_s:
                last_reclaim = now
                orphaned = await job_queue.reclaim_orphaned(idle_ms=settings.chat_job_claim_idle_ms)
                for entry in orphaned:
                    logger.warning("Reclaimed orphaned chat job", extra={"request_id": entry[1].get("request_id")})
                    await _process(chat_service, job_queue, entry)

            for entry in await job_queue.read_new(block_ms=2000):
                await _process(chat_service, job_queue, entry)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one bad iteration must not kill the worker
            logger.exception("Chat job worker loop error")
            await asyncio.sleep(1)
    logger.info("Chat job worker stopped")


async def _process(chat_service: ChatService, job_queue: ChatJobQueue, entry: JobEntry) -> None:
    message_id, job = entry
    prepared = PreparedChat(
        conversation_id=job["conversation_id"],
        request_id=job["request_id"],
        model=job["model"],
        provider=job["provider"],
        messages=job["messages"],
        is_new=False,
    )
    try:
        await chat_service.run_and_publish(prepared, user_id=job["user_id"], session_id=job["session_id"])
    except Exception:  # noqa: BLE001 - a poison-pill job must not wedge the queue forever
        logger.exception("Chat job failed", extra={"request_id": job.get("request_id")})
    finally:
        # Always ack: leaving it unacked would only be useful if retrying
        # a *logic* failure could succeed differently next time, which it
        # can't (same job, same LLM call). Unacked retries exist for
        # process-crash recovery, handled separately by reclaim_orphaned.
        await job_queue.ack(message_id)
