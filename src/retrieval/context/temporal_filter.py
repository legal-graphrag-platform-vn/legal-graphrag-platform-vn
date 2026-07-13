"""Deterministic temporal filtering for half-open legal validity intervals."""

from src.retrieval.models import RetrievedUnit, TemporalQuery


class TemporalFilter:
    def filter(
        self,
        units: list[RetrievedUnit],
        temporal: TemporalQuery,
        *,
        preserve_versions: bool = False,
    ) -> list[RetrievedUnit]:
        if not temporal.has_temporal:
            return (
                sorted(units, key=_stable_rank_key)
                if preserve_versions
                else self._resolve_explicit_version_families(units)
            )
        if temporal.resolved_from is None:
            raise ValueError("Temporal query requires resolved_from")

        query_end = temporal.resolved_to or temporal.resolved_from
        valid_units = [
            unit
            for unit in units
            if unit.effective_from is not None
            and unit.effective_from <= query_end
            and (
                unit.effective_to is None or unit.effective_to > temporal.resolved_from
            )
        ]
        return (
            sorted(valid_units, key=_stable_rank_key)
            if preserve_versions
            else self._resolve_explicit_version_families(valid_units)
        )

    def filter_and_resolve(
        self, units: list[RetrievedUnit], temporal: TemporalQuery
    ) -> list[RetrievedUnit]:
        """Compatibility entrypoint; version-chain resolution belongs to graph traversal."""

        return self.filter(units, temporal)

    def _resolve_explicit_version_families(
        self, units: list[RetrievedUnit]
    ) -> list[RetrievedUnit]:
        resolved: dict[str, RetrievedUnit] = {}
        ungrouped: list[RetrievedUnit] = []
        for unit in units:
            if not unit.version_family_id:
                ungrouped.append(unit)
                continue
            current = resolved.get(unit.version_family_id)
            if current is None or _effective_ordinal(unit) > _effective_ordinal(
                current
            ):
                resolved[unit.version_family_id] = unit
        return sorted([*ungrouped, *resolved.values()], key=_stable_rank_key)


def _stable_rank_key(unit: RetrievedUnit) -> tuple[float, str]:
    return (-(unit.final_score or unit.graph_score or 0.0), unit.id)


def _effective_ordinal(unit: RetrievedUnit) -> int:
    return unit.effective_from.toordinal() if unit.effective_from else 0
