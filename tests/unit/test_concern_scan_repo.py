"""Tests for ConcernScanRepository — cache get/save roundtrip + key behaviour."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from openbourse.db.repositories import ConcernScanRepository, hash_concerns
from openbourse.domain import ConcernFinding


class TestHashConcerns:
    def test_order_invariant(self) -> None:
        assert hash_concerns(["A", "B"]) == hash_concerns(["B", "A"])

    def test_whitespace_invariant(self) -> None:
        assert hash_concerns(["A"]) == hash_concerns(["  A  "])

    def test_case_sensitive(self) -> None:
        # "SBC" and "sbc" likely mean different things to the user; cache
        # must distinguish them.
        assert hash_concerns(["SBC"]) != hash_concerns(["sbc"])

    def test_different_lists_get_different_hashes(self) -> None:
        assert hash_concerns(["A"]) != hash_concerns(["A", "B"])


class TestConcernScanRepository:
    async def test_returns_none_when_uncached(self, db_session: AsyncSession) -> None:
        repo = ConcernScanRepository(db_session)
        assert (
            await repo.get(accession_number="0001-23-456789", concerns=["A"]) is None
        )

    async def test_save_and_retrieve_roundtrip(self, db_session: AsyncSession) -> None:
        repo = ConcernScanRepository(db_session)
        findings = [
            ConcernFinding(concern="A", status="flagged", note="quote"),
            ConcernFinding(concern="B", status="clear", note=""),
        ]
        await repo.save(
            accession_number="0001-23-456789",
            concerns=["A", "B"],
            findings=findings,
            model="claude-test",
        )
        await db_session.flush()

        cached = await repo.get(
            accession_number="0001-23-456789", concerns=["B", "A"]
        )
        assert cached is not None
        assert {f.concern for f in cached} == {"A", "B"}
        flagged = next(f for f in cached if f.concern == "A")
        assert flagged.status == "flagged"
        assert flagged.note == "quote"

    async def test_different_concern_set_misses_cache(
        self, db_session: AsyncSession
    ) -> None:
        repo = ConcernScanRepository(db_session)
        await repo.save(
            accession_number="0001-23-456789",
            concerns=["A"],
            findings=[ConcernFinding(concern="A", status="flagged", note="")],
            model="claude-test",
        )
        await db_session.flush()
        # Different concern list — should miss.
        assert (
            await repo.get(
                accession_number="0001-23-456789", concerns=["A", "B"]
            )
            is None
        )

    async def test_save_replaces_existing_entry(
        self, db_session: AsyncSession
    ) -> None:
        repo = ConcernScanRepository(db_session)
        await repo.save(
            accession_number="0001-23-456789",
            concerns=["A"],
            findings=[ConcernFinding(concern="A", status="unknown", note="")],
            model="m1",
        )
        await db_session.flush()
        await repo.save(
            accession_number="0001-23-456789",
            concerns=["A"],
            findings=[ConcernFinding(concern="A", status="flagged", note="evidence")],
            model="m2",
        )
        await db_session.flush()

        cached = await repo.get(accession_number="0001-23-456789", concerns=["A"])
        assert cached is not None
        assert cached[0].status == "flagged"
        assert cached[0].note == "evidence"
