"""Periodic worker: deadlines, hub loss, lighting gate, candidates, scoring jobs.

Runs every `worker_interval_s` even when no client polls. Scoring happens outside any
database transaction: claim (tx) -> score (network, no lock) -> finish (tx).
"""
from __future__ import annotations

import asyncio
import logging

from . import lifecycle, matcher
from .config import Config
from .db import Database

log = logging.getLogger("vexo.worker")


class Engine:
    def __init__(self, db: Database, cfg: Config):
        self.db = db
        self.cfg = cfg
        self._scoring: set[str] = set()

    def sweep(self) -> list:
        with self.db.tx() as conn:
            return lifecycle.sweep(conn, self.cfg, self.db.now())

    def score_job(self, job_id: str) -> None:
        """Claim, score and finish one job synchronously (used by tests and the async loop)."""
        with self.db.tx() as conn:
            claimed = lifecycle.claim_job(conn, job_id, self.db.now(), self.cfg)
        if claimed is None:
            return
        _job, (a, b) = claimed
        result, error = None, None
        try:
            result = matcher.score(a, b, self.cfg.scorer)
        except matcher.ScoringUnavailable as exc:
            error = str(exc)
        except Exception as exc:                 # a scorer bug must not wedge the worker
            log.exception("scorer crashed")
            error = f"{type(exc).__name__}: {exc}"
        with self.db.tx() as conn:
            lifecycle.finish_job(conn, job_id, result, error, self.db.now(), self.cfg)

    def run_once(self) -> None:
        """One full synchronous pass: sweep, then score everything that is pending."""
        for job_id in self.sweep():
            self.score_job(job_id)

    async def run_forever(self) -> None:
        while True:
            try:
                jobs = await asyncio.to_thread(self.sweep)
                for job_id in jobs:
                    if job_id not in self._scoring:
                        self._scoring.add(job_id)
                        asyncio.create_task(self._score_async(job_id))
            except Exception:
                log.exception("worker sweep failed")
            await asyncio.sleep(self.cfg.worker_interval_s)

    async def _score_async(self, job_id: str) -> None:
        try:
            await asyncio.to_thread(self.score_job, job_id)
        finally:
            self._scoring.discard(job_id)
